import asyncio
from datetime import datetime, timezone
import logging
from uuid import uuid4
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from agentic.schemas.response import ChatResponse

logger=logging.getLogger(__name__)

class Runtime:
    def __init__(self,graph,store,saver,settings):
        self.graph,self.store,self.saver,self.settings=graph,store,saver,settings

    # cấu hình cho 1 lượt chạy (thread_id) 
    def config(self,thread_id):
        return {'configurable':{'thread_id':thread_id},'recursion_limit':self.settings.MAX_GRAPH_STEPS}

    # Truy xuất state của graph runner 
    async def state(self,thread_id): #thread_id -- định danh 1 lượt chạy trong 1 session_id (Graph Runner)
        if not thread_id: return None
        return await self.graph.aget_state(self.config(thread_id))

    # Đọc lại data từ checkpoint
    async def journal_snapshot(self, snapshot):
        if not snapshot or not snapshot.values:
            return
        try:
            checkpoint_id = (snapshot.config or {}).get('configurable',{}).get('checkpoint_id')
            await self.store.record_execution_state(snapshot.values, checkpoint_id)
        except Exception as exc:
            logger.warning('kg_journal_deferred error_type=%s', type(exc).__name__)

    # Chạy reconcile_forever() để đồng bộ các checkpoint với backend
    async def reconcile_forever(self):
        from agentic.memory.reconcile import reconcile_checkpoints
        while True:
            try:
                await reconcile_checkpoints(self.store.pool)
            except Exception as exc:
                logger.warning('kg_reconcile_deferred error_type=%s', type(exc).__name__)
            await asyncio.sleep(getattr(self.settings,'KG_RECONCILE_SECONDS',5))

    # Trả response --> frontend
    def response(self,state):
        pending=state.get('pending_action')
        is_pending=state.get('status')=='pending_confirmation'
        return ChatResponse(session_id=state['session_id'],run_id=state['run_id'],
            reply='Vui lòng kiểm tra và xác nhận thao tác trước khi lưu.' if is_pending else state.get('reply') or state.get('error') or '',
            status=state.get('status','failed') if state.get('status') in {'completed','needs_input','pending_confirmation','failed'} else 'failed',
            intent=state.get('decision',{}).get('intent'),pending_action=pending if is_pending else None,
            sources=state.get('sources',[]),tool_outputs=state.get('tool_outputs',[]))

    async def run(self,input,thread_id,emit=None):
        config=self.config(thread_id) # Lấy cấu hình
        try:
            async with asyncio.timeout(self.settings.RUN_TIMEOUT_SECONDS):
                async for update in self.graph.astream(input,config,stream_mode='updates'): #loop liên tục --> Phát hiện update node --> cập nhật state
                    for node,values in update.items():
                        if node=='__interrupt__': continue
                        logger.info('agent_step',extra={'thread_id':thread_id,'node':node,'status':(values or {}).get('status')})
                        if emit:
                            await emit({'type':'progress','node':node})
        except Exception as exc:
            logger.warning('agent_run_failed',extra={'thread_id':thread_id,'error_type':type(exc).__name__})
            snapshot=await self.state(thread_id)
            await self.journal_snapshot(snapshot)
            state=dict(snapshot.values) if snapshot else {}
            state.update(status='failed',reply='Lượt xử lý chưa hoàn tất. Có thể thử xác nhận lại cùng action_id để khôi phục thao tác đã duyệt.')
            return self.response(state)
        snapshot=await self.state(thread_id)
        await self.journal_snapshot(snapshot)
        telemetry = snapshot.values.get('telemetry',{})
        logger.info('agent_run_metrics',extra={'run_id':thread_id,'llm_calls':telemetry.get('llm_calls',0),
                    'input_tokens':telemetry.get('input_tokens',0),'output_tokens':telemetry.get('output_tokens',0)})
        return self.response(snapshot.values)

    async def chat(self,payload,user_id,emit=None):
        async with self.store.session(payload.session_id,user_id) as session:
            old=await self.state(session['thread_id'])
            previous=old.values if old else {}
            action=previous.get('pending_action')
            if action:
                row=await self.store.action(action['action_id'])
                if row and row['status'] in {'approved','executed'} and not row['response']:
                    raise HTTPException(409,'Recover the accepted action through /chat/confirm before starting another turn')
                if row and row['status']=='pending' and payload.message.strip().lower().rstrip('.!') in {'đồng ý','ok','yes','xác nhận','approve'}:
                    return self.response(previous)
            await self.store.invalidate(payload.session_id)
            history=[m for m in previous.get('messages',[]) if m.type=='human' or getattr(m,'name',None)=='orchestration_agent'][-40:]
            if previous.get('tool_outputs'):
                import json
                history.append(SystemMessage(content='Kết quả lượt trước (dữ liệu tham khảo, chưa phải hành động mới): '+json.dumps(previous['tool_outputs'],ensure_ascii=False)))
            thread_id=str(uuid4())
            initial={'messages':[*history,HumanMessage(content=payload.message)],'user_id':user_id,
                     'session_id':payload.session_id,'run_id':thread_id,'tool_outputs':[], 'tool_count':0,
                     'session_generation':session['generation'],
                     'research_count':0,'sources':[],'candidate':None,'pending_action':None,'status':'running','error':None,
                     'graph_context':None,'graph_retrieval_attempted':False,'graph_context_run_id':None,
                     'fast_read_plan':None,'fast_read_complete':False,'telemetry':{},'execution_records':[]}
            await self.graph.aupdate_state(self.config(thread_id),initial,as_node='__start__')
            await self.store.bind(payload.session_id,thread_id)
            return await self.run(None,thread_id,emit)

    async def confirm(self,payload,user_id,emit=None):
        async with self.store.session(payload.session_id,user_id,create=False) as session:
            try:
                from uuid import UUID
                UUID(payload.action_id)
            except ValueError:
                raise HTTPException(404,'Action not found') from None
            row=await self.store.action(payload.action_id)
            if not row or str(row['user_id'])!=user_id or row['session_id']!=payload.session_id:
                raise HTTPException(404,'Action not found')
            action=row['data']
            if action['revision']!=payload.revision:
                raise HTTPException(409,'Stale action revision')
            if row['status'] in {'superseded','expired','failed'}:
                raise HTTPException(409,'Action is no longer confirmable; request a new preview')
            if row['status']=='rejected' and payload.decision!='reject' or row['status'] in {'approved','executed'} and payload.decision!='approve':
                raise HTTPException(409,'Action decision cannot be changed')
            if row['response']:
                return ChatResponse.model_validate(row['response'])
            if row['status']=='pending':
                if datetime.fromisoformat(action['expires_at'])<=datetime.now(timezone.utc):
                    await self.store.set_action(payload.action_id,'expired')
                    raise HTTPException(409,'Confirmation expired; request a new preview')
                await self.store.set_action(payload.action_id,'approved' if payload.decision=='approve' else 'rejected')
            snapshot=await self.state(session['thread_id'])
            if not snapshot or snapshot.values.get('pending_action',{}).get('action_id')!=payload.action_id:
                # An executed action may have advanced to the next pending action
                # before the API process died. Return that checkpoint's response.
                if row['status']=='executed' and snapshot:
                    result=self.response(snapshot.values)
                    await self.store.set_action(payload.action_id,'executed',result.model_dump(mode='json'))
                    return result
                raise HTTPException(409,'Action does not belong to the active workflow')
            interrupted=any(t.interrupts for t in snapshot.tasks)
            if not snapshot.next:
                # An unknown write result ended with a friendly error; retry the
                # approved execution node, never regenerate the action.
                await self.graph.aupdate_state(self.config(session['thread_id']),{'approved':True,'status':'running','error':None},as_node='confirmation')
            result=await self.run(Command(resume={'decision':payload.decision}) if interrupted else None,session['thread_id'],emit)
            latest=await self.store.action(payload.action_id)
            if latest['status'] in {'executed','rejected','failed'}:
                await self.store.set_action(payload.action_id,latest['status'],result.model_dump(mode='json'))
            return result

    async def history(self,session_id,user_id):
        async with self.store.session(session_id,user_id,create=False) as session:
            snapshot=await self.state(session['thread_id'])
            values=snapshot.values if snapshot else {}
            msgs=[{'role':m.type,'content':m.content,'name':getattr(m,'name',None)} for m in values.get('messages',[])
                  if m.type=='human' or getattr(m,'name',None)=='orchestration_agent']
            status=values.get('status')
            pending=values.get('pending_action') if status=='pending_confirmation' else None
            return {'session_id':session_id,'message_count':len(msgs),'messages':msgs,
                    'status':status,'pending_action':pending,'sources':values.get('sources',[])}

    async def sessions(self,user_id):
        rows=await self.store.list_sessions(user_id)
        items=[]
        for row in rows:
            snapshot=await self.state(row['thread_id'])
            values=snapshot.values if snapshot else {}
            msgs=[m for m in values.get('messages',[]) if m.type=='human' or getattr(m,'name',None)=='orchestration_agent']
            human_msgs=[m for m in msgs if m.type=='human']
            title=(human_msgs[0].content.strip()[:60] if human_msgs else 'Cuộc trò chuyện mới')
            last_msg=(msgs[-1].content.strip()[:90] if msgs else '')
            created_at=row.get('created_at')
            items.append({
                'session_id':row['session_id'],
                'title':title,
                'last_message':last_msg,
                'message_count':len(msgs),
                'status':values.get('status') or 'idle',
                'created_at':created_at.isoformat() if hasattr(created_at,'isoformat') else str(created_at or '')
            })
        return {'sessions':items}

    async def clear(self,session_id,user_id):
        async with self.store.session(session_id,user_id,create=False) as session:
            snapshot=await self.state(session['thread_id'])
            pending=snapshot.values.get('pending_action') if snapshot else None
            if pending:
                row=await self.store.action(pending['action_id'])
                if row and row['status']=='approved':
                    raise HTTPException(409,'Recover the approved action before clearing history')
            # Each turn has its own thread. Delete all thread ids recorded for
            # this session, including superseded checkpoints, not just the latest.
            for thread in await self.store.threads(session_id):
                await self.saver.adelete_thread(thread)
            await self.store.delete_session(session_id)
            return {'session_id':session_id,'status':'cleared'}

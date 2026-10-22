import asyncio
from time import perf_counter
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from agentic.core.state import AgentState
from agentic.agents.orchestration_agent import OrchestrationAgent
from agentic.agents.tool_agent import ToolAgent
from agentic.agents.web_research_agent import WebResearchAgent
from agentic.core.context import request_context
from agentic.core.knowledge_helpers import latest_request, pilot_domain, PILOT_DOMAINS, make_fast_read_plan
from agentic.core.telemetry import MeasuredModels, active_metrics


def build_workflow(models, store, saver, tavily, settings, graph_context=None):
    models=MeasuredModels(models)
    orchestrator=OrchestrationAgent(models,settings)
    tool=ToolAgent(models,store,settings)
    research=WebResearchAgent(models,tavily,store,settings)
    graph=StateGraph(AgentState)

    async def guarded(fn,state,node):
        started=perf_counter()
        metrics={}
        marker=active_metrics.set(metrics)
        try:
            result=await fn(state)
        except Exception as exc:
            # Exceptions may contain upstream request bodies. Expose only class.
            result={'status':'failed','error':'Không hoàn tất bước xử lý ('+type(exc).__name__+').'}
        finally:
            active_metrics.reset(marker)
        previous=state.get('telemetry') or {}
        telemetry=dict(previous) if previous.get('run_id')==state.get('run_id') else {'run_id':state.get('run_id')}
        for key in ('llm_calls','input_tokens','output_tokens','model_ms'):
            telemetry[key]=telemetry.get(key,0)+metrics.get(key,0)
        telemetry['nodes']=[*telemetry.get('nodes',[]),{'name':node,'duration_ms':round((perf_counter()-started)*1000,3),
                                                     'llm_calls':metrics.get('llm_calls',0)}][-settings.MAX_GRAPH_STEPS:]
        if 'retrieval' in metrics:
            telemetry['retrieval']=metrics['retrieval']
        result['telemetry']=telemetry
        return result

    async def retrieve(state, domain):
        mode=getattr(settings,'KG_MODE','off')
        if mode=='off' or domain not in PILOT_DOMAINS or (state.get('graph_retrieval_attempted') and state.get('graph_context_run_id')==state.get('run_id')):
            return {}
        update={'graph_retrieval_attempted':True,'graph_context_run_id':state.get('run_id'),'graph_context':None}
        started=perf_counter()
        status='unavailable'
        try:
            ctx=request_context.get()
            if ctx.user_id!=state['user_id']:
                status='blocked'
            elif graph_context is not None:
                timeout=min(getattr(settings,'KG_RETRIEVAL_TIMEOUT_MS',150),150)/1000
                context=await asyncio.wait_for(graph_context.retrieve(
                    authenticated_user_id=ctx.user_id,session_id=state['session_id'],
                    message=latest_request(state),domain_hint=domain),timeout=timeout)
                data=context.model_dump(mode='json')
                status=data.get('status','unavailable')
                if mode in {'advisory','optimized'} and status in {'ok','empty'}:
                    update['graph_context']=data
        except (asyncio.TimeoutError,TimeoutError):
            status='timeout'
        except Exception:
            # KG outages never turn a usable backend/LLM workflow into a failure.
            status='unavailable'
        metrics=active_metrics.get()
        if metrics is not None:
            metrics['retrieval']={'status':status,'duration_ms':round((perf_counter()-started)*1000,3)}
        return update

    async def decide_step(state):
        update=await retrieve(state,pilot_domain(latest_request(state)))
        current={**state,**update}
        result=await orchestrator.decide(current)
        current.update(result)
        plan=None
        if getattr(settings,'KG_MODE','off')=='optimized' and current.get('graph_context'):
            plan=make_fast_read_plan(current)
        return {**update,**result,'fast_read_plan':plan.model_dump(mode='json') if plan else None,'fast_read_complete':False}

    async def decide(state):
        result=await guarded(decide_step,state,'orchestrator')
        if result.get('status')=='failed' and 'decision' not in result:
            result['decision']={'action':'answer','instruction':'Thông báo không thể phân loại yêu cầu.'}
        return result

    async def answer(state):
        result=await guarded(orchestrator.answer,state,'answer')
        if 'reply' not in result:
            from langchain_core.messages import AIMessage
            result['reply']=state.get('error') or 'Dịch vụ trả lời hiện không khả dụng. Vui lòng thử lại.'
            result['messages']=[AIMessage(content=result['reply'],name='orchestration_agent')]
        return result

    async def await_confirmation(state):
        decision=interrupt(state['pending_action'])
        if decision.get('decision')=='approve':
            return {'approved':True}
        from langchain_core.messages import AIMessage
        reply='Đã từ chối thao tác; không ghi dữ liệu.'
        return {'approved':False,'pending_action':None,'status':'completed','reply':reply,'messages':[AIMessage(content=reply,name='orchestration_agent')]}

    graph.add_node('orchestrator',decide)
    async def tool_step(state):
        update=await retrieve(state,state.get('decision',{}).get('domain'))
        current={**state,**update}
        if getattr(settings,'KG_MODE','off')=='optimized' and current.get('graph_context') and not current.get('fast_read_plan'):
            plan=make_fast_read_plan(current)
            if plan:
                update['fast_read_plan']=plan.model_dump(mode='json')
                current.update(update)
        result=await tool.invoke_fast(current)
        if result is None:
            result=await tool.invoke(current)
        if result.get('fast_read_complete') and not result.get('pending_action') and result.get('status')=='running':
            result['decision']={**state['decision'],'action':'answer','next_agent':'orchestrator',
                                'instruction':'Trả lời yêu cầu tiến độ theo kết quả backend đã xác minh.'}
        return {**update,**result}

    async def invoke_tool(state): return await guarded(tool_step,state,'tool')
    async def invoke_research(state): return await guarded(research.invoke,state,'research')
    async def execute(state): return await guarded(tool.execute,state,'execute')
    graph.add_node('tool',invoke_tool)
    graph.add_node('research',invoke_research)
    graph.add_node('confirmation',await_confirmation)
    graph.add_node('execute',execute)
    graph.add_node('answer',answer)
    graph.add_edge(START,'orchestrator')
    graph.add_conditional_edges('orchestrator',lambda s:s['decision']['action'] if s['decision']['action'] in {'tool','research'} else 'answer',
                                {'tool':'tool','research':'research','answer':'answer'})
    graph.add_conditional_edges('tool',lambda s:'confirmation' if s.get('pending_action') else ('answer' if s.get('fast_read_complete') and s.get('status')=='running' and s.get('decision',{}).get('action')=='answer' else 'orchestrator'))
    graph.add_edge('research','orchestrator')
    graph.add_conditional_edges('confirmation',lambda s:'execute' if s.get('approved') else END)
    graph.add_edge('execute','orchestrator')
    graph.add_edge('answer',END)
    return graph.compile(checkpointer=saver)

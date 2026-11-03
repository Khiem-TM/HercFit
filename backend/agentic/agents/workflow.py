from agentic.services.rag_pipeline import decision_domains, retrieve_graph_context
from agentic.observability import annotate
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from agentic.agents.state import AgentState
from agentic.agents.orchestration_agent import OrchestrationAgent
from agentic.agents.tool_agent import ToolAgent
from agentic.agents.research_agent import ResearchV2
from agentic.tools.policy import continue_catalog_lookup
from agentic.services.routing import (latest_request, make_fast_read_plan, fast_reads_enabled, fast_route,
                                           fast_answer_instruction, FastReadPlan)
from agentic.security.content_filter import assess
from agentic.services import food_suggestion
from agentic.knowledge_graph.service import domains_for
from agentic.observability.telemetry import MeasuredModels
from agentic.observability.execution import run_node
from agentic.core.context import request_context
from agentic.services import personal_context


def build_workflow(models, store, saver, tavily, settings, graph_context=None, jev=None):
    models=MeasuredModels(models)
    orchestrator=OrchestrationAgent(models,settings,jev=jev)
    tool=ToolAgent(models,store,settings)
    research=ResearchV2(models,tavily,store,settings,jev=jev)
    graph=StateGraph(AgentState)

    async def guarded(fn, state, node):
        return await run_node(fn, state, node, settings)


    async def decide_step(state):
        hinted=domains_for(latest_request(state))
        update=await retrieve_graph_context(state,hinted, settings=settings, graph_context=graph_context)
        current={**state,**update}
        routed=fast_route(current) if fast_reads_enabled(settings) and assess(latest_request(current)) is None else None
        if routed:
            # Lệnh đọc độc lập khớp một mẫu chặt chẽ: không gọi model định tuyến hay chọn tool.
            decision,plan=routed
            annotate(fast_route=plan.template_id)
            return {**update,'decision':decision,'status':'running','fast_read_plan':plan.model_dump(mode='json'),
                    'fast_read_complete':False,'turn':{'run_id':state.get('run_id'),'intent':decision['intent'],
                                                       'domain':decision['domain'],'action':decision['action']}}
        if (assess(latest_request(current)) is None and food_suggestion.is_food_suggestion(latest_request(current))
                and not current.get('tool_outputs') and not current.get('pending_action')
                and (state.get('turn') or {}).get('run_id') != state.get('run_id')):
            # Gợi ý bữa ăn độc lập: một lần tra catalog chỉ đọc, không gọi model định tuyến.
            decision=food_suggestion.lookup_decision()
            annotate(route='food_suggestion')
            return {**update,'decision':decision,'status':'running','fast_read_plan':None,'fast_read_complete':False,
                    'turn':{'run_id':state.get('run_id'),'intent':decision['intent'],'domain':decision['domain'],
                            'action':decision['action']}}
        if current.get('user_context_run_id')!=current.get('run_id'):
            # Một lần mỗi lượt chạy: những gì HercFit đã biết về người dùng, để router đọc thay vì hỏi.
            ctx=request_context.get(None)
            card=await personal_context.load_card(ctx.backend,ctx.token) if ctx else None
            update={**update,'user_context':card,'user_context_run_id':current.get('run_id')}
            current.update(update)
        result=await orchestrator.decide(current)
        current.update(result)
        decision=result.get('decision') or {}
        # Cách diễn đạt có thể không gọi tên miền graph nào ("pace 5K của tôi"): đọc ngay miền của router và
        # chủ đề cá nhân, để câu trả lời, ngữ cảnh và tra cứu thấy được thẻ, không chỉ các lời gọi tool.
        # Các miền bước này đã thử được để lại cho các bước sau (timeout không được thử lại ở đây).
        missed=[d for d in decision_domains(decision) if d not in hinted]
        if missed:
            update={**update,**await retrieve_graph_context(current,missed,settings=settings,graph_context=graph_context)}
            current.update(update)
        if (state.get('turn') or {}).get('run_id')!=state.get('run_id') and decision:
            # Quyết định định tuyến đầu tiên đặt tên cho lượt; các quyết định sau chỉ tiếp nối nó.
            result['turn']={'run_id':state.get('run_id'),'intent':decision.get('intent'),
                            'domain':decision.get('domain'),'action':decision.get('action')}
        plan=None
        if fast_reads_enabled(settings):
            plan=make_fast_read_plan(current)
        return {**update,**result,'fast_read_plan':plan.model_dump(mode='json') if plan else None,'fast_read_complete':False}

    async def decide(state):
        result=await guarded(decide_step,state,'orchestrator')
        if result.get('status')=='failed' and 'decision' not in result:
            result['decision']={'action':'answer','instruction':'Thông báo không thể phân loại yêu cầu.'}
        return result

    async def answer(state):
        if state.get('model_auth_failed'):
            # Model trả lời dùng chung thông tin xác thực này. Một request khác không thể
            # khắc phục lỗi 401 và sẽ che lỗi gốc bằng lỗi thứ hai.
            from langchain_core.messages import AIMessage
            reply = state['error']
            return {'reply':reply,'status':'failed',
                    'messages':[AIMessage(content=reply,name='orchestration_agent')]}
        result=await guarded(orchestrator.answer,state,'answer')
        if 'reply' not in result:
            from langchain_core.messages import AIMessage
            result['reply']=state.get('error') or 'Dịch vụ trả lời hiện không khả dụng. Vui lòng thử lại.'
            result['messages']=[AIMessage(content=result['reply'],name='orchestration_agent')]
        return result

    async def await_confirmation(state):
        decision=interrupt(state['pending_action'])
        if decision.get('decision')=='approve':
            # Bản người dùng sửa trên thẻ đã được runtime kiểm tra và lưu vào hành động đang chờ.
            edited=decision.get('action')
            return {'approved':True,**({'pending_action':{**state['pending_action'],**edited}} if edited else {})}
        from langchain_core.messages import AIMessage
        reply='Đã từ chối thao tác; không ghi dữ liệu.'
        return {'approved':False,'pending_action':None,'status':'completed','reply':reply,'messages':[AIMessage(content=reply,name='orchestration_agent')]}

    graph.add_node('orchestrator',decide)
    async def tool_step(state):
        update=await retrieve_graph_context(state,[state.get('decision',{}).get('domain')], settings=settings, graph_context=graph_context)
        current={**state,**update}
        if fast_reads_enabled(settings) and not current.get('fast_read_plan'):
            plan=make_fast_read_plan(current)
            if plan:
                update['fast_read_plan']=plan.model_dump(mode='json')
                current.update(update)
        result=await tool.invoke_fast(current)
        if result is None:
            meal=await tool.invoke_meal(current)
            if meal is not None and (meal.get('pending_action') or meal.get('prepared_reply')):
                result=meal
            elif meal is not None:
                # Có món chưa khớp chắc chắn: model dựng create_meals từ kết quả tra cứu vừa có (không tra lại).
                looked={**current,**meal,'messages':[*current.get('messages',[]),*meal['messages']]}
                result=await tool.invoke(looked)
                result={**meal,**result,'messages':[*meal['messages'],*result.get('messages',[])]}
            else:
                result=await tool.invoke(current)
        if result.get('fast_read_complete') and not result.get('pending_action') and result.get('status')=='running':
            plan=FastReadPlan.model_validate(current['fast_read_plan'])
            result['decision']={**state['decision'],'action':'answer','next_agent':'orchestrator',
                                'instruction':fast_answer_instruction(plan)}
        elif food_suggestion.lookup_completed(current, result):
            # Lần tra catalog là toàn bộ việc đọc: trả lời từ đó (dùng lại cạnh đọc nhanh).
            result.update(status='running', fast_read_complete=True,
                          decision={**state['decision'],'action':'answer','next_agent':'orchestrator',
                                    'instruction':food_suggestion.ANSWER_INSTRUCTION})
        return {**update,**result}

    async def context_step(state):
        decision=state['decision']
        topic=decision.get('topic') or 'general'
        reads=personal_context.deep_reads(topic)
        inventory=(state.get('user_context') or {}).get('inventory') or {}
        if not inventory.get('health_shared_with_assistant'):
            # Dữ liệu thiết bị chỉ khi người dùng đồng ý (backend cũng kiểm tra điều này).
            reads=[(name,args) for name,args in reads if not name.startswith(('get_health','list_'))]
        result=await tool.read_context(state,reads) if reads else {}
        outputs={o['tool']:o for o in result.get('tool_outputs',[])}
        trace={'stage':'context','topic':topic,'reads':[{'tool':name,'ok':bool((outputs.get(name) or {}).get('ok'))}
                                                         for name,_ in reads]}
        annotate(personal_topic=topic, personal_reads=len(reads))
        return {**result,'personal_reads_done':True,'route_trace':[*(state.get('route_trace') or []),trace]}

    async def invoke_tool(state): return await guarded(tool_step,state,'tool')
    async def invoke_context(state): return await guarded(context_step,state,'context')
    async def invoke_research(state): return await guarded(research.invoke,state,'research')
    async def execute(state): return await guarded(tool.execute,state,'execute')
    graph.add_node('tool',invoke_tool)
    graph.add_node('research',invoke_research)
    graph.add_node('context',invoke_context)
    graph.add_node('confirmation',await_confirmation)
    graph.add_node('execute',execute)
    graph.add_node('answer',answer)
    graph.add_edge(START,'orchestrator')
    def after_orchestrator(s):
        decision=s['decision']
        if decision.get('personalize') and not s.get('personal_reads_done') and decision['action'] in {'research','answer'}:
            return 'context'  # dữ liệu của người dùng trước bước tra cứu hoặc trả lời
        return decision['action'] if decision['action'] in {'tool','research'} else 'answer'
    graph.add_conditional_edges('orchestrator',after_orchestrator,
                                {'tool':'tool','research':'research','answer':'answer','context':'context'})
    graph.add_conditional_edges('context',lambda s:'research' if s['decision']['action']=='research' else 'answer',
                                {'research':'research','answer':'answer'})
    # Câu trả lời do code viết (những gì lệnh ghi đã xác nhận đã lưu) kết thúc lượt mà không gọi định tuyến thêm.
    graph.add_conditional_edges('tool',lambda s:'confirmation' if s.get('pending_action') else
        ('tool' if continue_catalog_lookup(s) else
         ('answer' if s.get('status')=='running' and (s.get('prepared_reply') or (
             s.get('fast_read_complete') and s.get('decision',{}).get('action')=='answer')) else 'orchestrator')))
    # Câu trả lời cá nhân hoá được viết từ dữ liệu của người dùng và bằng chứng tra cứu, dù tra cứu tìm được gì.
    graph.add_conditional_edges('research',lambda s:'answer' if (s.get('decision') or {}).get('personalize') or s.get('research_answer')
                                or s.get('prepared_reply') or s.get('status') in {'needs_input','failed'} else 'orchestrator')
    graph.add_conditional_edges('confirmation',lambda s:'execute' if s.get('approved') else END)
    # Lệnh finalize bị từ chối với 409 quay lại dưới dạng bản xem trước mới cần được xác nhận riêng.
    graph.add_conditional_edges('execute',lambda s:'confirmation' if s.get('status')=='pending_confirmation' else 'orchestrator')
    graph.add_edge('answer',END)
    return graph.compile(checkpointer=saver)

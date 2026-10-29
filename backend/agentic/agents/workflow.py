from agentic.services.rag_pipeline import retrieve_graph_context
from observability import annotate
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
from knowledge_graph.service import domains_for
from agentic.observability.telemetry import MeasuredModels
from agentic.observability.execution import run_node


def build_workflow(models, store, saver, tavily, settings, graph_context=None, jev=None):
    models=MeasuredModels(models)
    orchestrator=OrchestrationAgent(models,settings,jev=jev)
    tool=ToolAgent(models,store,settings)
    research=ResearchV2(models,tavily,store,settings,jev=jev)
    graph=StateGraph(AgentState)

    async def guarded(fn, state, node):
        return await run_node(fn, state, node, settings)


    async def decide_step(state):
        update=await retrieve_graph_context(state,domains_for(latest_request(state)), settings=settings, graph_context=graph_context)
        current={**state,**update}
        routed=fast_route(current) if fast_reads_enabled(settings) and assess(latest_request(current)) is None else None
        if routed:
            # Standalone read matched a strict template: no routing or tool-selection model call.
            decision,plan=routed
            annotate(fast_route=plan.template_id)
            return {**update,'decision':decision,'status':'running','fast_read_plan':plan.model_dump(mode='json'),
                    'fast_read_complete':False,'turn':{'run_id':state.get('run_id'),'intent':decision['intent'],
                                                       'domain':decision['domain'],'action':decision['action']}}
        if (assess(latest_request(current)) is None and food_suggestion.is_food_suggestion(latest_request(current))
                and not current.get('tool_outputs') and not current.get('pending_action')
                and (state.get('turn') or {}).get('run_id') != state.get('run_id')):
            # Standalone meal suggestion: one read-only catalog lookup, no routing model call.
            decision=food_suggestion.lookup_decision()
            annotate(route='food_suggestion')
            return {**update,'decision':decision,'status':'running','fast_read_plan':None,'fast_read_complete':False,
                    'turn':{'run_id':state.get('run_id'),'intent':decision['intent'],'domain':decision['domain'],
                            'action':decision['action']}}
        result=await orchestrator.decide(current)
        current.update(result)
        decision=result.get('decision') or {}
        if (state.get('turn') or {}).get('run_id')!=state.get('run_id') and decision:
            # The first routing decision names the turn; later ones only continue it.
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
            # The answer model shares these credentials. Another request cannot
            # recover a 401 and would hide the original failure with a second one.
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
            return {'approved':True}
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
            result=await tool.invoke(current)
        if result.get('fast_read_complete') and not result.get('pending_action') and result.get('status')=='running':
            plan=FastReadPlan.model_validate(current['fast_read_plan'])
            result['decision']={**state['decision'],'action':'answer','next_agent':'orchestrator',
                                'instruction':fast_answer_instruction(plan)}
        elif food_suggestion.lookup_completed(current, result):
            # The catalog lookup is the whole read: answer from it (reuses the fast-read edge).
            result.update(status='running', fast_read_complete=True,
                          decision={**state['decision'],'action':'answer','next_agent':'orchestrator',
                                    'instruction':food_suggestion.ANSWER_INSTRUCTION})
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
    graph.add_conditional_edges('tool',lambda s:'confirmation' if s.get('pending_action') else
        ('tool' if continue_catalog_lookup(s) else
         ('answer' if s.get('fast_read_complete') and s.get('status')=='running' and s.get('decision',{}).get('action')=='answer' else 'orchestrator')))
    graph.add_conditional_edges('research',lambda s:'answer' if s.get('research_answer') or s.get('prepared_reply') or s.get('status') in {'needs_input','failed'} else 'orchestrator')
    graph.add_conditional_edges('confirmation',lambda s:'execute' if s.get('approved') else END)
    # A finalize rejected with 409 comes back as a fresh preview that needs its own confirmation.
    graph.add_conditional_edges('execute',lambda s:'confirmation' if s.get('status')=='pending_confirmation' else 'orchestrator')
    graph.add_edge('answer',END)
    return graph.compile(checkpointer=saver)

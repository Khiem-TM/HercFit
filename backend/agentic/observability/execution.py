"""Consistent node errors, latency, model usage and JEV billing across the graph."""
import logging
from time import perf_counter
from openai import AuthenticationError
from agentic.observability import annotate
from agentic.observability.telemetry import active_metrics, merge_jev_metrics

logger = logging.getLogger(__name__)


async def run_node(fn, state, node, settings):
    started=perf_counter()
    metrics={}
    marker=active_metrics.set(metrics)
    try:
        from agentic.observability.node_span import span
        with span(getattr(settings,'LANGSMITH_ENABLED',False),node,state.get('run_id')):
            result=await fn(state)
    except Exception as exc:
        # Exceptions may contain upstream request bodies. Expose only class;
        # Never write raw exception text to operational logs.
        logger.warning('agent_node_failed node=%s error_type=%s',node,type(exc).__name__)
        annotate(status='failed', error_code=type(exc).__name__)
        result={'status':'failed','error':'Không hoàn tất bước xử lý ('+type(exc).__name__+').'}
        if isinstance(exc, AuthenticationError) or type(exc).__name__ == 'OpenAIAuthenticationError':
            provider = getattr(settings, 'DEFAULT_PROVIDER', 'model')
            result.update(model_auth_failed=True,
                          error=f'Không xác thực được model ({provider}). Kiểm tra khóa API của nhà cung cấp trong cấu hình agent và khởi động lại dịch vụ.')
    finally:
        active_metrics.reset(marker)
    previous=state.get('telemetry') or {}
    telemetry=dict(previous) if previous.get('run_id')==state.get('run_id') else {'run_id':state.get('run_id')}
    if telemetry.get('llm_calls') and not telemetry.get('billing_version'):
        # Resumed checkpoints from before billing instrumentation have no
        # verified historical price/usage completeness; never call them free.
        telemetry['llm_cost_unknown_calls'] = telemetry.get('llm_cost_unknown_calls', 0) + telemetry['llm_calls']
        telemetry['llm_usage_unknown_calls'] = telemetry.get('llm_usage_unknown_calls', 0) + telemetry['llm_calls']
    telemetry['billing_version'] = 1
    for key in ('llm_calls','input_tokens','output_tokens','model_ms','llm_cost','llm_cost_unknown_calls','llm_usage_unknown_calls'):
        telemetry[key]=telemetry.get(key,0)+metrics.get(key,0)
    merge_jev_metrics(telemetry, metrics.get('jev_events', []))
    telemetry['nodes']=[*telemetry.get('nodes',[]),{'name':node,'duration_ms':round((perf_counter()-started)*1000,3),
                                                 'llm_calls':metrics.get('llm_calls',0)}][-settings.MAX_GRAPH_STEPS:]
    if 'retrieval' in metrics:
        telemetry['retrieval']=metrics['retrieval']
    result['telemetry']=telemetry
    decision = result.get('decision') or {}
    annotate(node=node, domain=decision.get('domain') or (state.get('decision') or {}).get('domain'), research=node == 'research' or bool(state.get('research_count')))
    if result.get('status') == 'failed':
        annotate(status='failed', error_code='NodeFailed')
    return result

"""Bounded graph retrieval stage; ResearchV2 composes the document RAG stages.

Knowledge graph outages degrade to the existing backend/model path. No retrieval
result can authorize tools or change the authenticated request identity.
"""
import asyncio
from time import perf_counter
from agentic.observability import annotate
from agentic.knowledge_graph.service import PILOT_DOMAINS
from agentic.core.context import request_context
from agentic.services.routing import latest_request
from agentic.observability.telemetry import active_metrics, merge_retrieval

# Personal-context topics (services.personal_context.TOPICS) and the graph domain holding their data.
TOPIC_DOMAINS={'running':'trainings','strength':'trainings','training':'trainings','nutrition':'meals',
               'body':'metrics','recovery':'recovery'}


def decision_domains(decision):
    """Graph domains named by a routing decision: its domain and its personal topic."""
    decision=decision or {}
    return [d for d in dict.fromkeys([decision.get('domain'),TOPIC_DOMAINS.get(decision.get('topic'))]) if d in PILOT_DOMAINS]


async def retrieve_graph_context(state, domains, *, settings, graph_context=None):
    fresh=state.get('graph_context_run_id')==state.get('run_id')
    covered=list(state.get('graph_context_domains') or []) if fresh else []
    wanted=[d for d in dict.fromkeys([*covered,*domains]) if d in PILOT_DOMAINS]
    # Retrieve again only when routing reaches a domain the first hint missed. Without a
    # composed graph service (offline evaluation baselines) there is nothing to read.
    if graph_context is None or not set(wanted)-set(covered):
        return {}
    # Domains count as covered only after a successful read, so a timeout is retried later in the run.
    update={'graph_retrieval_attempted':True,'graph_context_run_id':state.get('run_id'),'graph_context_domains':covered,
            'graph_context':state.get('graph_context') if fresh else None}
    started=perf_counter()
    status='unavailable'
    try:
        ctx=request_context.get()
        if ctx.user_id!=state['user_id']:
            status='blocked'
        else:
            timeout=min(getattr(settings,'KG_RETRIEVAL_TIMEOUT_MS',150),150)/1000
            context=await asyncio.wait_for(graph_context.retrieve(
                authenticated_user_id=ctx.user_id,session_id=state['session_id'],
                message=latest_request(state),domain_hint=wanted),timeout=timeout)
            data=context.model_dump(mode='json')
            status=data.get('status','unavailable')
            if status in {'ok','empty'}:
                update['graph_context_domains']=wanted
                update['graph_context']=data
    except (asyncio.TimeoutError,TimeoutError):
        status='timeout'
    except Exception:
        # KG outages never turn a usable backend/LLM workflow into a failure.
        status='unavailable'
    duration=round((perf_counter()-started)*1000,3)
    metrics=active_metrics.get()
    if metrics is not None:
        # A node may read twice (request hint, then the router's domain): keep both attempts.
        metrics['retrieval']=merge_retrieval(metrics.get('retrieval'),{'status':status,'duration_ms':duration,'domains':wanted})
    annotate(status=status, duration_ms=duration)
    return update

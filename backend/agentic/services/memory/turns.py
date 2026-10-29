"""Structured summary of one conversation turn for the knowledge graph.

Only routing facts are kept: the first decision's domain/action, which tools
ran, whether a write was made or requested and the final status. Messages,
replies, tool arguments and the model's free-form intent text never leave.
"""
from agentic.tools.registry import REGISTRY
from agentic.knowledge_graph.intents import classify

TERMINAL = {'completed', 'needs_input', 'pending_confirmation', 'failed'}


def turn_record(state):
    run_id, status = state.get('run_id'), state.get('status')
    if not run_id or status not in TERMINAL:
        return None
    first = state.get('turn') or {}
    if first.get('run_id') != run_id:
        first = {}
    last = state.get('decision') or {}
    domain = first.get('domain') or last.get('domain')
    records = [record for record in state.get('execution_records') or [] if record.get('tool')]
    wrote = bool(state.get('pending_action')) or any(
        getattr(REGISTRY.get(record['tool']), 'write', False) and record.get('status') == 'succeeded' for record in records)
    researched = bool(state.get('research_count')) or first.get('action') == 'research'
    refs = []
    for record in records:
        for ref in record.get('resource_refs') or []:
            if ref not in refs:
                refs.append(ref)
    return {'run_id': run_id, 'session_id': state.get('session_id'), 'domain': domain,
            'intent': classify(domain, first.get('intent') or last.get('intent'), wrote=wrote, researched=researched),
            'action': first.get('action') or last.get('action'), 'status': status,
            'tools': sorted({record['tool'] for record in records})[:8], 'resource_refs': refs[:10]}

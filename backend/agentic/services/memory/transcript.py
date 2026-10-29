"""Session transcript helpers: pure functions, no Redis or model calls.

A turn mirrors what the chat history shows: the run's user message and the
orchestration_agent replies after it. Tool calls, tool results and system
notes stay in checkpoints only.
"""
import json

from agentic.tools.registry import REGISTRY

AGENT = 'orchestration_agent'
# Records worth remembering by name; reports and analytics are recomputed instead.
ENTITY_DOMAINS = {'metrics', 'goals', 'meals', 'trainings', 'foods', 'exercises', 'training_plans'}
NAME_FIELDS = ('name_vi', 'name', 'title', 'name_en')
TIME_FIELDS = ('consumed_at', 'started_at', 'recorded_at', 'start_date')
LIST_ENTITIES = 3
GAP_MESSAGE_CHARS = 500
TITLE_CHARS = 60
LAST_MESSAGE_CHARS = 90


def visible(messages):
    """What the person sees: their own messages and the agent's final replies."""
    return [m for m in messages or [] if m.type == 'human' or getattr(m, 'name', None) == AGENT]


def _message(message):
    content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
    return {'id': message.id, 'role': message.type, 'name': getattr(message, 'name', None), 'content': content}


def turn_from_state(values):
    """This run's turn: the last user message and the replies that follow it."""
    messages = visible(values.get('messages'))
    start = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].type == 'human'), None)
    if not values.get('run_id') or start is None:
        return None
    return {'run_id': values['run_id'], 'status': values.get('status'),
            'messages': [_message(m) for m in messages[start:]]}


def seed_turns(values):
    """Split a checkpoint window into turns; only the newest has a known run ID."""
    turns = []
    for message in visible(values.get('messages')):
        if message.type == 'human' or not turns:
            turns.append({'run_id': f'legacy:{message.id or len(turns)}', 'status': 'completed', 'messages': []})
        turns[-1]['messages'].append(_message(message))
    if turns and values.get('run_id') and turns[-1]['messages'][0]['role'] == 'human':
        turns[-1].update(run_id=values['run_id'], status=values.get('status'))
    return turns


def _records(output):
    data = output.get('output')
    if isinstance(data, dict) and isinstance(data.get('record'), dict):
        data = data['record']
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)][:LIST_ENTITIES]
    return [data] if isinstance(data, dict) else []


def entities_from_state(values):
    """Records the run read or wrote, newest first. IDs come only from backend outputs."""
    found = []
    for output in reversed(values.get('tool_outputs') or []):
        spec = REGISTRY.get(output.get('tool') or '')
        # A deleted record is not something to refer back to.
        if not output.get('ok') or spec is None or spec.domain not in ENTITY_DOMAINS or spec.method == 'DELETE':
            continue
        for record in _records(output):
            if record.get('id'):
                found.append({'kind': spec.domain, 'id': str(record['id']),
                              'name': next((str(record[k]) for k in NAME_FIELDS if record.get(k)), None),
                              'at': next((str(record[k]) for k in TIME_FIELDS if record.get(k)), None)})
    return found


def merge_entities(previous, current, seq, limit):
    merged, seen = [], set()
    for entity in [*({**item, 'seq': seq} for item in current), *previous]:
        key = (entity.get('kind'), entity.get('id'))
        if key not in seen:
            seen.add(key)
            merged.append(entity)
    return merged[:limit]


def outside_messages(message_count, covered, window):
    """Messages that are neither summarized nor in the verbatim window."""
    return max(0, message_count - covered - window)


def gap_turns(turns, outside):
    """Oldest unsummarized turns with at least one message outside the window."""
    selected = []
    for turn in turns:
        if outside <= 0:
            break
        selected.append(turn)
        outside -= len(turn['messages'])
    return selected


def fold_plan(turns, outside, max_chars):
    """Oldest unsummarized turns lying wholly outside the window, within a prompt budget."""
    selected, used = [], 0
    for turn in turns:
        size = sum(len(m['content']) for m in turn['messages'])
        if len(turn['messages']) > outside or (selected and used + size > max_chars):
            break
        selected.append(turn)
        outside -= len(turn['messages'])
        used += size
    return selected


def _clip(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def render_memory(summary, gap, entities, limit):
    """One bounded block. Truncation drops records first, then recent turns, then the summary."""
    sections = []
    if summary:
        sections.append('Tóm tắt các lượt trước:\n' + summary.strip())
    if gap:
        lines = ['- ' + ('Người dùng' if m['role'] == 'human' else 'Trợ lý') + ': ' + _clip(m['content'], GAP_MESSAGE_CHARS)
                 for turn in gap for m in turn['messages']]
        sections.append('Các lượt trước chưa được tóm tắt:\n' + '\n'.join(lines))
    if entities:
        lines = ['- ' + ' · '.join(part for part in (e.get('kind'), e.get('name'), e.get('at'), 'id=' + str(e.get('id'))) if part)
                 for e in entities]
        sections.append('Bản ghi đã nhắc trong phiên (ID nội bộ để tra cứu, không hiển thị cho người dùng):\n' + '\n'.join(lines))
    text = '\n\n'.join(sections)
    return text if len(text) <= limit else text[:limit] + '…(rút gọn)'

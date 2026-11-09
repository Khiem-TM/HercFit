"""Giao việc song song cho các agent chuyên trách.

Supervisor tách một tin nhắn nhiều ý thành 2–3 nhiệm vụ của các agent khác nhau (ví dụ ghi bữa ăn, ghi buổi tập, đọc
số đo). Mỗi agent chạy trên bản sao riêng của state (LangGraph Send) nên các nhánh không tranh nhau khoá state; nút
join gộp kết quả theo thứ tự nhiệm vụ.

Chỉ phần việc chuẩn bị chạy song song: đọc dữ liệu và dựng bản xem trước. Lệnh ghi vẫn qua cổng xác nhận, từng thẻ một
theo thứ tự nhiệm vụ. Nhánh cần hỏi thêm, cần tra cứu catalog/web, còn bữa ăn kế tiếp hoặc lỗi thì được làm tiếp tuần
tự bằng đường định tuyến thường sau các thẻ, nên không phần nào của yêu cầu bị bỏ dở.
"""
from agentic.core import roster
from agentic.observability.telemetry import merge_branches
from agentic.tools.registry import REGISTRY

MAX_TASKS = 3
INTENT_LOG_FOOD = 'LOG_FOOD'
ANSWER_INSTRUCTION = ('Trả lời từng phần của yêu cầu theo kết quả các agent trong lượt này: phần đọc dữ liệu nêu đúng '
                      'số liệu đã đọc; phần đã lưu do HercFit tự báo; phần người dùng từ chối (rejected) thì nói chưa lưu.')
# State riêng của một nhánh: các kết quả của lượt bắt đầu trống để join gộp đúng phần nhánh tạo ra.
BRANCH_RESET = {'tool_outputs': [], 'execution_records': [], 'route_trace': [], 'telemetry': {}, 'pending_action': None,
                'pending_queue': [], 'prepared_reply': None, 'status': 'running', 'error': None, 'fast_read_plan': None,
                'fast_read_complete': False, 'catalog_handoff': None, 'research_handoff': None, 'clarification': None,
                'catalog_choice': None, 'food_gap': None}


def plan(decision, policy):
    """Quyết định định tuyến cho từng nhiệm vụ, hoặc None khi lượt đi đường tuần tự: cần 2–3 nhiệm vụ, mỗi nhiệm vụ
    một agent khác nhau, mọi miền được chế độ trò chuyện cho phép."""
    items = decision.get('tasks') or []
    owners = [roster.specialist_for(item.get('domain')) for item in items]
    if not 2 <= len(items) <= MAX_TASKS or None in owners or len(set(owners)) != len(owners):
        return None
    if not all(policy.allows(item['domain']) for item in items):
        return None
    tasks = []
    for index, item in enumerate(items):
        task = {'intent': item['intent'], 'action': 'tool', 'next_agent': 'tool', 'domain': item['domain'],
                'instruction': item['instruction'], 'missing_fields': [], 'objectives': [item['instruction']],
                'writes_before': 0, 'task_index': index}
        if item['intent'] == INTENT_LOG_FOOD and decision.get('meal_log'):
            task['meal_log'] = decision['meal_log']  # đường nhanh ghi bữa ăn dùng bản nháp của router
        tasks.append(task)
    return tasks


def branch(state, task):
    """State riêng của một nhánh: hội thoại và ngữ cảnh của lượt, quyết định là nhiệm vụ của nhánh."""
    return {**{k: v for k, v in state.items() if k != 'agent_results'}, **BRANCH_RESET, 'decision': task}


def outcome(agent, start, result):
    """Phần nhánh tạo ra, để join gộp: tin nhắn mới, kết quả tool, bản xem trước và nhánh đã xong việc hay chưa."""
    decision = result.get('decision') or {}
    meals = decision.get('meal_log') or []
    meals_left = 0 < int(decision.get('meal_log_next') or 0) < len(meals)
    pending = result.get('pending_action')
    resolved = (result.get('status') in {'running', 'pending_confirmation'} and not meals_left
                and not result.get('catalog_handoff') and not result.get('research_handoff')
                and not result.get('candidate') and not result.get('food_gap'))
    outputs = result.get('tool_outputs') or []
    reads = resolved and not pending and any(
        o.get('ok') and not getattr(REGISTRY.get(o.get('tool') or ''), 'write', False) for o in outputs)
    return {'index': start['decision']['task_index'], 'agent': agent, 'domain': start['decision']['domain'],
            'messages': list(result.get('messages') or [])[len(start.get('messages') or []):],
            'tool_outputs': outputs, 'execution_records': result.get('execution_records') or [],
            'tool_calls': (result.get('tool_count') or 0) - (start.get('tool_count') or 0),
            'route_trace': result.get('route_trace') or [], 'telemetry': result.get('telemetry') or {},
            'pending_action': pending, 'status': result.get('status'), 'error': result.get('error'),
            'resolved': resolved, 'reads': reads}


def join(state):
    """Gộp các nhánh theo thứ tự nhiệm vụ. Bản xem trước đầu tiên lên thẻ, các bản sau vào hàng đợi; mọi nhánh xong
    việc thì trả lời, còn không thì định tuyến thường làm tiếp phần còn lại."""
    results = sorted(state.get('agent_results') or [], key=lambda r: r['index'])
    decision = state.get('decision') or {}
    pendings = [r['pending_action'] for r in results if r.get('pending_action')]
    unresolved = [r['agent'] for r in results if not r['resolved']]
    resolved = not unresolved and len(results) == len(decision.get('delegated_tasks') or [])
    trace = {'stage': 'join', 'agents': [r['agent'] for r in results], 'pending': len(pendings), 'unresolved': unresolved}
    return {
        'agent_results': None,
        'messages': [m for r in results for m in r['messages']],
        'tool_outputs': [*(state.get('tool_outputs') or []), *(o for r in results for o in r['tool_outputs'])],
        'execution_records': [*(state.get('execution_records') or []), *(e for r in results for e in r['execution_records'])],
        'tool_count': (state.get('tool_count') or 0) + sum(r['tool_calls'] for r in results),
        'route_trace': [*(state.get('route_trace') or []), *(t for r in results for t in r['route_trace']), trace],
        'telemetry': merge_branches(state.get('telemetry'), [r['telemetry'] for r in results]),
        'pending_action': pendings[0] if pendings else None,
        'pending_queue': pendings[1:],
        'status': 'pending_confirmation' if pendings else 'running',
        'error': None,
        # Phần còn dở đi qua router (writes_before None: luật write_done không kết thúc lượt sớm).
        'decision': {**decision, 'next_agent': 'orchestrator', 'reads': any(r['reads'] for r in results),
                     **({'action': 'answer', 'instruction': ANSWER_INSTRUCTION} if resolved else
                        {'action': 'delegate', 'writes_before': None})},
    }


def answers(state):
    """Lượt giao việc song song đã xong mọi nhánh: sau các thẻ thì trả lời, không định tuyến lại."""
    decision = state.get('decision') or {}
    return bool(decision.get('delegated_tasks')) and decision.get('action') == 'answer'


def next_card(state, result):
    """Sau một lệnh ghi đã thực thi (hoặc lỗi), đưa bản xem trước kế tiếp trong hàng đợi lên thẻ."""
    queue = list(state.get('pending_queue') or [])
    if not queue or result.get('pending_action') or result.get('status') == 'pending_confirmation':
        return result
    return {**result, 'pending_action': queue[0], 'pending_queue': queue[1:], 'status': 'pending_confirmation'}


def after_reject(state):
    """Người dùng từ chối một thẻ của lượt giao việc song song: các thẻ còn lại vẫn được hỏi, rồi lượt tiếp tục.
    None cho lượt thường (giữ cách kết thúc cũ)."""
    decision = state.get('decision') or {}
    if not decision.get('delegated_tasks'):
        return None
    action_id = (state.get('pending_action') or {}).get('action_id')
    outputs = [{**o, 'rejected': True} if o.get('pending') and o.get('action_id') == action_id else o
               for o in state.get('tool_outputs') or []]
    queue = list(state.get('pending_queue') or [])
    update = {'approved': False, 'tool_outputs': outputs}
    if queue:
        return {**update, 'pending_action': queue[0], 'pending_queue': queue[1:], 'status': 'pending_confirmation'}
    return {**update, 'pending_action': None, 'pending_queue': [], 'status': 'running'}

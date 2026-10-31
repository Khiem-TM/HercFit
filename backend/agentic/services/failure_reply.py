"""Code-owned reply for a failed turn: what was saved, what was not, and how to continue.

A model-written reply to a failed turn (run 195ff084) presented a dinner and the day's
total as logged: only the new food record had been saved, the meal step had timed out
and nothing was in the meal journal. A failed turn therefore never reaches the model;
its reply is built from the executed writes alone.
"""

# Executed writes, as the user would name them.
WRITES = {
    'create_foods': 'Món mới trong danh mục thực phẩm', 'finalize_foods': 'Món trong danh mục thực phẩm',
    'create_exercises': 'Bài tập mới trong danh mục', 'finalize_exercises': 'Bài tập trong danh mục',
    'create_meals': 'Bữa ăn trong nhật ký', 'update_meals': 'Bữa ăn đã sửa', 'delete_meals': 'Đã xoá bữa ăn',
    'create_trainings': 'Buổi tập trong nhật ký', 'update_trainings': 'Buổi tập đã sửa', 'delete_trainings': 'Đã xoá buổi tập',
    'create_metrics': 'Số đo cơ thể', 'update_metrics': 'Số đo đã sửa', 'delete_metrics': 'Đã xoá số đo',
    'create_goals': 'Mục tiêu', 'update_goals': 'Mục tiêu đã sửa', 'complete_goal': 'Hoàn thành mục tiêu',
    'cancel_goal': 'Huỷ mục tiêu', 'create_plan': 'Kế hoạch', 'create_training_plans': 'Lịch tập',
    'update_training_plans': 'Lịch tập đã sửa', 'end_training_plan': 'Kết thúc lịch tập',
}
# The journal write a logging request is for; the reply says when it did not happen.
JOURNALS = {'LOG_FOOD': ('create_meals', 'bữa ăn này vào nhật ký, nên tổng calo hôm nay chưa thay đổi'),
            'LOG_EXERCISE': ('create_trainings', 'buổi tập này vào nhật ký, nên calo tiêu hao hôm nay chưa thay đổi')}
CAUSES = {
    'TimeoutError': 'Mô hình AI phản hồi quá thời gian chờ nên mình chưa hoàn tất yêu cầu.',
    'APIConnectionError': 'Không kết nối được tới mô hình AI nên mình chưa hoàn tất yêu cầu.',
    'RateLimitError': 'Mô hình AI đang quá tải nên mình chưa hoàn tất yêu cầu.',
}
NODE_ERROR = 'Không hoàn tất bước xử lý ('


def cause(error: str | None) -> str:
    """User-facing reason: node exceptions by class, other errors are already written for the user."""
    error = (error or '').strip()
    if not error:
        return 'Có lỗi khi xử lý nên mình chưa hoàn tất yêu cầu.'
    if error.startswith(NODE_ERROR):
        name = error[len(NODE_ERROR):].rstrip(').')
        return next((text for key, text in CAUSES.items() if name.endswith(key)), 'Có lỗi khi xử lý nên mình chưa hoàn tất yêu cầu.')
    return error


def saved_writes(state) -> list[tuple[str, str | None]]:
    """(tool, record name) of each write the backend executed in this turn."""
    saved = []
    for output in state.get('tool_outputs') or []:
        if output.get('ok') and output.get('action_id') and output.get('tool') in WRITES:
            data = output.get('output') if isinstance(output.get('output'), dict) else {}
            saved.append((output['tool'], data.get('name_vi') or data.get('name')))
    return saved


def failure_reply(state) -> str:
    saved = saved_writes(state)
    lines = ['⚠️ ' + cause(state.get('error'))]
    if saved:
        lines += ['', 'Đã lưu:'] + [f'- {WRITES[tool]}' + (f': {name}' if name else '') for tool, name in saved]
    intent = (state.get('turn') or {}).get('intent') or (state.get('decision') or {}).get('intent')
    journal = JOURNALS.get(intent)
    if journal and journal[0] not in {tool for tool, _ in saved}:
        lines += ['', 'Chưa lưu: ' + journal[1] + '.']
    elif not saved:
        lines += ['', 'Chưa có dữ liệu nào được lưu.']
    lines += ['', 'Bạn gửi lại yêu cầu để mình làm tiếp' + (' — mục đã lưu sẽ được dùng lại, không tạo trùng.' if saved else '.')]
    return '\n'.join(lines)

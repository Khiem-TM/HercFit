"""Câu trả lời do code viết cho lượt thất bại: những gì đã lưu, những gì chưa, và cách tiếp tục.

Một câu trả lời do model viết cho lượt thất bại (lượt chạy 195ff084) trình bày bữa tối và tổng
của ngày như đã ghi: thực ra chỉ bản ghi thực phẩm mới được lưu, bước ghi bữa ăn đã timeout
và nhật ký bữa ăn không có gì. Vì vậy lượt thất bại không bao giờ đến model;
câu trả lời của nó chỉ được dựng từ các lệnh ghi đã thực thi.
"""

# Các lệnh ghi đã thực thi, theo cách người dùng sẽ gọi tên chúng.
WRITES = {
    'create_foods': 'Món mới trong danh mục thực phẩm', 'finalize_foods': 'Món trong danh mục thực phẩm',
    'create_exercises': 'Bài tập mới trong danh mục', 'finalize_exercises': 'Bài tập trong danh mục',
    'create_meals': 'Bữa ăn trong nhật ký', 'update_meals': 'Bữa ăn đã sửa', 'delete_meals': 'Đã xoá bữa ăn',
    'create_trainings': 'Buổi tập trong nhật ký', 'update_trainings': 'Buổi tập đã sửa', 'delete_trainings': 'Đã xoá buổi tập',
    'create_metrics': 'Số đo cơ thể', 'update_metrics': 'Số đo đã sửa', 'delete_metrics': 'Đã xoá số đo',
    'create_goals': 'Mục tiêu', 'update_goals': 'Mục tiêu đã sửa', 'complete_goal': 'Hoàn thành mục tiêu',
    'cancel_goal': 'Huỷ mục tiêu', 'create_training_plans': 'Lịch tập',
    'update_training_plans': 'Lịch tập đã sửa', 'end_training_plan': 'Kết thúc lịch tập',
}
# Lệnh ghi nhật ký mà một yêu cầu ghi hướng tới; câu trả lời nói rõ khi nó không xảy ra.
JOURNALS = {'LOG_FOOD': ('create_meals', 'bữa ăn này vào nhật ký, nên tổng calo hôm nay chưa thay đổi'),
            'LOG_EXERCISE': ('create_trainings', 'buổi tập này vào nhật ký, nên calo tiêu hao hôm nay chưa thay đổi')}
CAUSES = {
    'TimeoutError': 'Mô hình AI phản hồi quá thời gian chờ nên mình chưa hoàn tất yêu cầu.',
    'APIConnectionError': 'Không kết nối được tới mô hình AI nên mình chưa hoàn tất yêu cầu.',
    'RateLimitError': 'Mô hình AI đang quá tải nên mình chưa hoàn tất yêu cầu.',
}
NODE_ERROR = 'Không hoàn tất bước xử lý ('


def cause(error: str | None) -> str:
    """Lý do hiển thị cho người dùng: exception của node theo lớp, các lỗi khác đã được viết sẵn cho người dùng."""
    error = (error or '').strip()
    if not error:
        return 'Có lỗi khi xử lý nên mình chưa hoàn tất yêu cầu.'
    if error.startswith(NODE_ERROR):
        name = error[len(NODE_ERROR):].rstrip(').')
        return next((text for key, text in CAUSES.items() if name.endswith(key)), 'Có lỗi khi xử lý nên mình chưa hoàn tất yêu cầu.')
    return error


def saved_writes(state) -> list[tuple[str, str | None]]:
    """(tool, tên bản ghi) của mỗi lệnh ghi mà backend đã thực thi trong lượt này."""
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

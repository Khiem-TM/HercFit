"""Phiên bản 6: hướng dẫn catalog cho tool model khi món ăn không còn tra cứu web (xem routing.py cùng phiên bản)."""
from agentic.prompts.v1.domains import CAPABILITY_GUIDANCE as _V1_CAPABILITY
from agentic.prompts.v6.routing import _revise

CAPABILITY_GUIDANCE = _revise(_V1_CAPABILITY, (
    ('Khi ghi meals, bạn được đọc list_foods/get_foods/resolve_foods.\n',
     'Khi ghi meals, bạn được đọc list_foods/get_foods.\n'),
    ('Catalog rỗng: chuyển Orchestrator sang research foods/exercises; nhiều biến thể thì hỏi bằng tên.\n',
     'Catalog không có món ăn: dừng lại, không đoán món gần giống và không tra web (HercFit hiện thẻ tìm món/tạo món\n'
     'riêng). Catalog không có bài tập: chuyển Orchestrator sang research exercises. Nhiều biến thể thì hỏi bằng tên.\n'),
))

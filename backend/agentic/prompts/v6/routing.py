"""Phiên bản 6: món ăn không còn tra cứu web.

Catalog chưa có món cần ghi thì router vẫn giao cho agent dinh dưỡng (action tool, domain meals); HercFit hỏi người
dùng bằng thẻ món thiếu (tìm món trong catalog hoặc tạo món riêng, services/food_gap.py). Research catalog chỉ còn cho
bài tập. Phần còn lại giữ nguyên v2 (chế độ đầy đủ/Plan) và v3 (chế độ ghi nhanh); hai bản đó được giữ cố định.
"""
from agentic.prompts.v2.routing import ROUTING_PROMPT as _V2_ROUTING
from agentic.prompts.v3.routing import NORMAL_ROUTING_PROMPT as _V3_NORMAL


def _revise(text, changes):
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError('Prompt base changed: ' + old[:60])
        text = text.replace(old, new)
    return text


FOOD_RULES = (
    ('Ưu tiên catalog. Nhiều kết quả gần giống thì hỏi người dùng chọn. Chỉ research food/exercise\n'
     'khi catalog không có kết quả phù hợp hoặc người dùng yêu cầu web rõ ràng.\n',
     'Ưu tiên catalog. Nhiều kết quả gần giống thì hỏi người dùng chọn. Món ăn không bao giờ research: catalog chưa có\n'
     'món cần ghi thì vẫn là action tool domain meals (HercFit hiện thẻ tìm món/tạo món riêng). Chỉ research exercise\n'
     'khi catalog không có kết quả phù hợp hoặc người dùng yêu cầu web rõ ràng.\n'),
    ('research_query chỉ chứa tên món ăn/bài tập công khai,',
     'research_query chỉ chứa tên bài tập hoặc câu hỏi kiến thức công khai,'),
    ('Khi có candidate đã kiểm chứng (có finalization) và cần lưu, chuyển tool domain foods/exercises: Tool Agent\n'
     'gửi nguyên command finalize đã ký. Catalog không có món/bài tập cần ghi: action research với domain\n'
     'foods/exercises và research_query là tên công khai của món/bài tập.\n',
     'Khi có candidate đã kiểm chứng (có finalization) và cần lưu, chuyển tool domain exercises: Tool Agent\n'
     'gửi nguyên command finalize đã ký. Catalog không có bài tập cần ghi: action research với domain\n'
     'exercises và research_query là tên công khai của bài tập.\n'),
    ('Đang ghi món/bài tập (lượt trước hỏi số liệu hoặc catalog chưa có) mà người dùng nhờ tìm web, hoặc chỉ gửi lại tên món:\n'
     'vẫn là ghi nhật ký (LOG_FOOD/LOG_EXERCISE), action research với domain foods/exercises, không phải câu hỏi kiến thức.\n',
     'Đang ghi món/bài tập (lượt trước hỏi số liệu hoặc catalog chưa có) mà người dùng nhờ tìm web, hoặc chỉ gửi lại tên:\n'
     'vẫn là ghi nhật ký, không phải câu hỏi kiến thức: món ăn là LOG_FOOD action tool domain meals; bài tập là\n'
     'LOG_EXERCISE action research domain exercises.\n'),
)

ROUTING_PROMPT = _revise(_V2_ROUTING, FOOD_RULES)
NORMAL_ROUTING_PROMPT = _revise(_V3_NORMAL, FOOD_RULES)

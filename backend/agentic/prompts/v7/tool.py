"""Phiên bản 7: món riêng người dùng tự đưa số liệu luôn tính theo gam/ml (không còn serving_unit PORTION)."""
from agentic.prompts.v1.tool import PROMPT as _V1_PROMPT
from agentic.prompts.v6.routing import _revise

PROMPT = _revise(_V1_PROMPT, (
    ('create_foods đúng số liệu đó (đồ uống/suất\n'
     'không rõ gram dùng serving_unit PORTION), không bịa trường còn thiếu.',
     'create_foods đúng số liệu đó: serving_size\n'
     'là lượng gam/ml mà số liệu áp dụng (serving_unit G hoặc ML), khẩu phần như "1 ly" thì thêm vào portions; chưa rõ\n'
     'gam/ml của suất thì hỏi lại, không bịa trường còn thiếu.'),
))

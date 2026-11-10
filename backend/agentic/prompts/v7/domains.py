"""Phiên bản 7: mọi món trong catalog tính theo 100 g hoặc 100 ml, không còn món theo suất (PORTION).

"1 tô", "1 suất" được quy ra gam/ml bằng khẩu phần hộ gia đình (portions) của món; lượng ghi luôn là G hoặc ML.
"""
from agentic.prompts.v6.domains import CAPABILITY_GUIDANCE as _V6_CAPABILITY
from agentic.prompts.v6.routing import _revise

CAPABILITY_GUIDANCE = _revise(_V6_CAPABILITY, (
    ('SERVING là đúng khẩu phần catalog: 1 tô/2 quả chỉ đổi thành 1/2 SERVING khi catalog xác định\n'
     'một serving là một tô/quả tương ứng. Nếu catalog chỉ có mỗi 100g, không coi 1 quả là 1 serving;\n'
     'hỏi trọng lượng hoặc tìm bản ghi theo quả/tô có nguồn. Giá trị chưa biết vẫn là null.\n'
     'Món có serving_unit PORTION: dinh dưỡng tính cho 1 suất; ghi bằng SERVING (1 suất = 1). Chỉ dùng gram\n'
     'khi món có portion_weight_g. Trường portions liệt kê khẩu phần hộ gia đình (ví dụ "1 tô lớn" = 650 G):\n'
     'dùng đúng quantity/unit đó khi người dùng nói theo bát, tô, quả.\n',
     'Mọi món tính dinh dưỡng theo serving_size gam (G) hoặc mililít (ML); lượng ăn luôn ghi bằng đúng serving_unit\n'
     'của món. Trường portions là khẩu phần hộ gia đình đo bằng đơn vị đó (ví dụ "1 tô" = 500 G): người dùng nói\n'
     '1 tô/2 cái/1 suất thì nhân số lượng với quantity của portions. Món không có portions thì hỏi khối lượng,\n'
     'không coi 1 quả là 100 g. Giá trị chưa biết vẫn là null.\n'),
    ('Ngoại lệ: cùng tên nhưng một bản tính mỗi 100 g và một bản PORTION (mỗi suất) là hai cách đo của cùng món:\n'
     'người dùng nói gram thì chọn bản 100 g, nói tô/bát/suất/đĩa thì chọn bản PORTION, không hỏi lại.\n',
     'Ngoại lệ: cùng tên một bản không có portions và một bản có portions là hai cách đo của cùng món: người dùng nói\n'
     'gram/ml thì chọn bản không có portions, nói tô/bát/suất/đĩa thì chọn bản có portions và quy ra gam theo\n'
     'portions, không hỏi lại.\n'),
))

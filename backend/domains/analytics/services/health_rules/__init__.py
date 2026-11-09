"""Bộ luật chỉ số sức khoẻ: ngưỡng cao/thấp theo thể trạng và mục tiêu, mỗi ngưỡng có nguồn y tế.

catalog   nguồn (Bộ Y tế → WHO → hội chuyên môn), ngưỡng và siêu dữ liệu của từng luật
features  gom chỉ số của một người dùng từ các service sẵn có (không điền 0 cho dữ liệu thiếu)
evaluate  hàm thuần: Features + Profile → các Signal (luật, nhãn, mức độ, giá trị, ngưỡng, bằng chứng)

LLM chỉ viết lời cho Signal đã có; nó không đặt ngưỡng, không đổi mức độ và không chẩn đoán.
"""

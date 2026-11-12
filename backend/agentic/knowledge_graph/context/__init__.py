"""Context Graph: G_C = f(G_K, q, u, t, i, s, p).

Mỗi câu hỏi rút ra một đồ thị ngữ cảnh con G_C từ đồ thị nền G_K bằng một truy vấn Cypher theo ý định i:
mẫu đã có (seed hoặc đã học) hoặc do Context Agent sinh ra. Model chỉ viết hình dạng truy vấn; chủ sở hữu u, khoảng
thời gian t và trạng thái phiên s đi vào bằng tham số do code gán, chính sách p do code thực thi (validator.py,
policy.py).
"""

"""Hàng đợi công việc PostgreSQL bền vững (bảng jobs, migration 0018).

queue.py   xếp hàng có dedupe, lấy job bằng SKIP LOCKED và fencing epoch,
           heartbeat, hoàn tất/thử lại/cần xử lý, bộ thu hồi
retry.py   lớp lỗi -> bước tiếp theo, backoff full-jitter
quota.py   token bucket cho quota nhà cung cấp (theo người dùng, theo project)
"""

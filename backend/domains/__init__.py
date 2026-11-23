"""Các miền nghiệp vụ: mỗi miền có models.py, schemas.py, services.py, routers.py (và module riêng khi cần).

Package của mỗi miền có model (mọi miền trừ analytics) nạp domains.registry trước tiên, nên import bất kỳ module nào
của miền đó cũng đăng ký đủ mọi model ORM (kể cả khi chỉ cần schema).
"""

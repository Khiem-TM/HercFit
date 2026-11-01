"""Các công tắc tính năng đọc từ settings (backend/.env).

READER_V2_DOMAINS chuyển từng bên dùng một sang các bản ghi của nền tảng sức khoẻ
(docs/GOOGLE_HEALTH_PLATFORM_2026-11-01.md). Mỗi miền đổi một hành vi
đã ghi trong tài liệu; danh sách rỗng giữ mọi bộ đọc ở hành vi v1.

  training   buổi chạy từ thiết bị (Google) được tính vào phân tích chạy bộ trừ khi có buổi
             nhập tay trùng thời gian; không tự đặt loại bài, RPE hay set cho chúng
  nutrition  lượng ăn theo ngày tính cả bữa ghi ở ứng dụng khác (nhật ký dinh dưỡng
             Google không gắn với bữa ăn HercFit)
  body       một lần cân thấy hai lần (nhập tay + cân trong vòng 10 phút, lệch <= 0,2 kg)
             chỉ tính một lần trong xu hướng cân nặng, ưu tiên bản nhập tay
  wellbeing  ngữ cảnh overview có bản tóm tắt sức khoẻ tinh thần chỉ gồm số đếm (cần
             consent nhạy cảm riêng; không bao giờ có tên triệu chứng hay tâm trạng)
  analytics  đường nền chỉ dùng các ngày đã trọn, lấy từ ANALYTICS_RECOMPUTE
             khi đã lưu, ngược lại tính trực tiếp bằng cùng thuật toán
  agent      trợ lý đọc dữ liệu sức khoẻ qua context API; các tool thô có route v1
             đã bị thay thế không được cung cấp (service agent, cùng .env)
"""
from __future__ import annotations

from core.settings import READER_V2_CHOICES, settings


def reader_v2(domain: str) -> bool:
    if domain not in READER_V2_CHOICES:
        raise ValueError(f"unknown reader domain {domain!r}")
    return domain in settings.READER_V2_DOMAINS


__all__ = ["READER_V2_CHOICES", "reader_v2"]

"""Cấu hình pytest chung: đưa backend/ vào sys.path và đặt biến môi trường trước khi import code ứng dụng.

Biến đặt ở đây ghi đè giá trị trong backend/.env (pydantic-settings ưu tiên biến môi trường), nên test không phụ thuộc
cấu hình dev: không gửi trace Langfuse, không chạy Jev, có khoá JWT cố định.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-for-production-0001"
os.environ["LANGFUSE_TRACING"] = "false"
os.environ["JEV_MODE"] = "off"

"""Thư mục tài nguyên cố định, không phụ thuộc thư mục làm việc của tiến trình."""

from pathlib import Path

AGENTIC_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = AGENTIC_ROOT.parent

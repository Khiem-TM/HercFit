"""Durable cleanup tickets survive failed uploads and process restarts."""
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class ImageCleanup(Base):
    __tablename__ = "image_cleanup"

    public_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cloud_name: Mapped[str] = mapped_column(Text, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ImageGenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "image_generation_jobs"

    story_chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_chapters.id"), nullable=False, index=True
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_image_urls: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    style_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    result_r2_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int] = mapped_column(Integer, default=1344)
    height: Mapped[int] = mapped_column(Integer, default=768)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

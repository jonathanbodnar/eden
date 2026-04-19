from __future__ import annotations

import uuid

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChapterSourceSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chapter_source_sets"

    chapter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    image_ref: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

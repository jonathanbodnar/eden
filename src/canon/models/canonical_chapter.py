from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin


class CanonicalChapter(UUIDPrimaryKeyMixin, VersionedMixin, TimestampMixin, Base):
    __tablename__ = "canonical_chapters"

    epoch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StoryOutline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "story_outlines"

    epoch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_epochs.id"), nullable=False, index=True
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    themes: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    time_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    regions: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    outline_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

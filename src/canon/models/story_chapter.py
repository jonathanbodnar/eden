from __future__ import annotations

import uuid

from sqlalchemy import ARRAY, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StoryChapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "story_chapters"

    story_outline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_outlines.id"), nullable=True, index=True
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_chapters.id"), nullable=True, index=True
    )
    epoch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_epochs.id"), nullable=False, index=True
    )
    narrative_text: Mapped[str] = mapped_column(Text, nullable=False)
    claims_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    image_prompts_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    entity_mentions_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    synthesis_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # V2 pipeline metadata
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")
    cluster_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archetypes_used: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

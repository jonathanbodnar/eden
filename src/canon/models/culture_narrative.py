from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base


class CultureNarrative(Base):
    __tablename__ = "culture_narratives"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    story_outline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_outlines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    culture_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    culture_label: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_text: Mapped[str] = mapped_column(Text, nullable=False)
    actors_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    events_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    places_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    source_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # V2 additions — Stage 1 of the deterministic-merge pipeline outputs both
    # a readable prose history (shown in the culture dropdown) and a strictly
    # structured fact sheet used by Stage 2 to distil atomic events.
    prose_history: Mapped[str | None] = mapped_column(Text, nullable=True)
    fact_sheet: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, server_default="0")
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CultureEventSkeleton(Base):
    __tablename__ = "culture_event_skeletons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    culture_narrative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("culture_narratives.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    story_outline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_outlines.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    culture_key: Mapped[str] = mapped_column(Text, nullable=False)
    events_json: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    unique_details: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

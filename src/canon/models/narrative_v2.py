"""Narrative Pipeline V2 — SQLAlchemy models.

Three new tables backing the deterministic-merge pipeline:

- ArchetypeRegistry: write-once, reused-forever archetype name map
- CultureAtomicEvent: strict-schema events with embeddings for clustering
- EventCluster: platform-computed merged event layer
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ArchetypeRegistry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global registry of archetype names used across all chapters.

    An archetype is the stable name the unified narrative uses for a role
    (e.g. "The Divine Craftsman"). Multiple culture-specific deities merge
    into one archetype. Once minted, an archetype is never renamed — later
    chapters that encounter the same role reuse the existing archetype.
    """

    __tablename__ = "archetype_registry"

    archetype_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="actor")
    classification_kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="primary"
    )
    also_known_as: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    canonical_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    role_signature: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    first_seen_chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_chapters.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_seen_epoch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_epochs.id", ondelete="SET NULL"),
        nullable=True,
    )
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CultureAtomicEvent(Base):
    """One atomic event extracted from a single culture's fact sheet.

    Strict schema: one verb, one primary actor set, one outcome. Feeds
    deterministic clustering in Stage 3.
    """

    __tablename__ = "culture_atomic_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    culture_narrative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("culture_narratives.id", ondelete="CASCADE"),
        nullable=False,
    )
    story_outline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_outlines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    culture_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    verb: Mapped[str] = mapped_column(Text, nullable=False)
    verb_family: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    objects: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    materials: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    place: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quoted_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stored as list of floats at the ORM layer; the underlying column is
    # vector(1536) via the migration. SQLAlchemy treats it as ARRAY(Float)
    # for read/write purposes — pgvector accepts both representations.
    action_embedding: Mapped[list[float] | None] = mapped_column(
        ARRAY(Float), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventCluster(Base):
    """One merged event across all contributing cultures.

    Built deterministically in Stage 3. One cluster = one telling in the
    final narrative. Preserves traceability back to every contributing
    atomic event.
    """

    __tablename__ = "event_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    story_outline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("story_outlines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_key: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_archetype_name: Mapped[str] = mapped_column(Text, nullable=False)
    archetype_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("archetype_registry.id", ondelete="SET NULL"),
        nullable=True,
    )
    contributing_event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    contributing_cultures: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    canonical_verb: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    verb_family: Mapped[str] = mapped_column(Text, nullable=False)
    materials: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vivid_details: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_quotes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    age_rank_of_oldest: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

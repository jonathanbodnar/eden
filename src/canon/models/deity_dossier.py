"""Deity Dossier + Archetype Merge Proposal models.

These back the audit-first archetype remerge workflow:

- DeityDossier: per-actor evidence packet built from existing data
  (atomic events + canonical actors + source dates + LLM-summarized
  characteristics). One row per (actor_name, epoch_id).
- ArchetypeMergeProposal: an LLM-generated verdict on an existing
  archetype — keep as-is, split into N groups, reassign actors, or
  merge with a sibling archetype. Pending until human approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeityDossier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Evidence packet for a single named actor in a single epoch."""

    __tablename__ = "deity_dossiers"

    actor_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    epoch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_epochs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_actors.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Aggregates from culture_atomic_events
    cultures: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    co_occurring_actors: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # Source dating (joined via canon_support_links → source_records → source_dates)
    earliest_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    earliest_source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    earliest_date_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    earliest_date_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    earliest_date_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    dating_confidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Representative source IDs used to build the characteristics summary
    source_passage_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_passage_excerpts: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # LLM-generated narrative dossier (2–3 paragraphs)
    characteristics_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Current archetype membership (denormalized for fast reads)
    current_archetype_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("archetype_registry.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_archetype_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArchetypeMergeProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An LLM verdict on whether an archetype's members actually belong together.

    The `proposed_groups` jsonb captures one or more groups; when there is
    a single group with all members, the verdict is effectively keep-as-is.
    When there are multiple groups, it's a split proposal. `proposal_kind`
    is a coarse classifier for the UI.
    """

    __tablename__ = "archetype_merge_proposals"

    epoch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_epochs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_archetype_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_archetype_names: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    proposal_kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="keep"
    )
    proposed_groups: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    overall_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending", index=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)

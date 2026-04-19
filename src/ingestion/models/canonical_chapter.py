"""Canonical chapters — explorable units within epochs."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalChapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_chapters"

    epoch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_epochs.id"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    epoch: Mapped["CanonicalEpoch"] = relationship("CanonicalEpoch", back_populates="chapters")

    actors: Mapped[list["CanonicalActor"]] = relationship(
        "CanonicalActor", secondary="chapter_actors", back_populates="chapters",
    )
    events: Mapped[list["CanonicalEvent"]] = relationship(
        "CanonicalEvent", secondary="chapter_events", back_populates="chapters",
    )
    places: Mapped[list["CanonicalPlace"]] = relationship(
        "CanonicalPlace", secondary="chapter_places", back_populates="chapters",
    )
    story_threads: Mapped[list["CanonicalStoryThread"]] = relationship(
        "CanonicalStoryThread", secondary="chapter_story_threads", back_populates="chapters",
    )
    motifs: Mapped[list["Motif"]] = relationship(
        "Motif", secondary="motif_assignments", back_populates="chapters",
    )

    source_sets: Mapped[list["ChapterSourceSet"]] = relationship(
        "ChapterSourceSet", back_populates="chapter", cascade="all, delete-orphan",
    )
    context_sets: Mapped[list["ChapterContextSet"]] = relationship(
        "ChapterContextSet", back_populates="chapter", cascade="all, delete-orphan",
    )
    artifact_sets: Mapped[list["ChapterArtifactSet"]] = relationship(
        "ChapterArtifactSet", back_populates="chapter", cascade="all, delete-orphan",
    )
    image_sets: Mapped[list["ChapterImageSet"]] = relationship(
        "ChapterImageSet", back_populates="chapter", cascade="all, delete-orphan",
    )

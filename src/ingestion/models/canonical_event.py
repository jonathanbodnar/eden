"""Canonical events — major historical events in the canon."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_events"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    chapters: Mapped[list["CanonicalChapter"]] = relationship(
        "CanonicalChapter", secondary="chapter_events", back_populates="events",
    )

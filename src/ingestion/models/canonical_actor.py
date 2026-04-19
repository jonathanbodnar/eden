"""Canonical actors — gods, kings, founders, beings in the canon."""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalActor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_actors"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    culture: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chapters: Mapped[list["CanonicalChapter"]] = relationship(
        "CanonicalChapter", secondary="chapter_actors", back_populates="actors",
    )

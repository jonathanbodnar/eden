"""Canonical epochs — broad time bands of ancient history."""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalEpoch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_epochs"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    epoch_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chapters: Mapped[list["CanonicalChapter"]] = relationship(
        "CanonicalChapter", back_populates="epoch", cascade="all, delete-orphan",
        order_by="CanonicalChapter.chapter_order",
    )

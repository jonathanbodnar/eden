from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin


class CanonicalEpoch(UUIDPrimaryKeyMixin, VersionedMixin, TimestampMixin, Base):
    __tablename__ = "canonical_epochs"

    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    epoch_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

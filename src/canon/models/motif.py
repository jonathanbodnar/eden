from __future__ import annotations

import uuid

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import CanonicalType


class Motif(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "motifs"

    label: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class MotifAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "motif_assignments"

    motif_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

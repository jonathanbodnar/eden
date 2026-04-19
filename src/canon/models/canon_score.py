from __future__ import annotations

import uuid

from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import CanonicalType


class CanonScore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canon_scores"

    canonical_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    age_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    corroboration_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    independence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    pattern_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    ambiguity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

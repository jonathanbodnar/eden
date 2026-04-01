from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import ReviewStatus, SegmentType


class Segment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "segments"

    source_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_versions.id"), nullable=False, index=True
    )
    segment_type: Mapped[SegmentType] = mapped_column(
        ENUM(SegmentType, name="segment_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    segment_order: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        ENUM(ReviewStatus, name="review_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=ReviewStatus.PENDING,
        nullable=False,
    )

    source_version = relationship("SourceVersion", back_populates="segments")
    embeddings = relationship("Embedding", back_populates="segment", cascade="all, delete-orphan")

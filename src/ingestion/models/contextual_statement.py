from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import (
    ContextType,
    ExtractionMethod,
    ReviewStatus,
    StatementConfidence,
)


class ContextualStatement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contextual_statements"

    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id"), nullable=False, index=True
    )
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_versions.id"), nullable=True, index=True
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id"), nullable=True, index=True
    )
    raw_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_objects.id"), nullable=True
    )

    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_type: Mapped[ContextType] = mapped_column(
        ENUM(ContextType, name="context_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    confidence: Mapped[StatementConfidence] = mapped_column(
        ENUM(StatementConfidence, name="statement_confidence", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=StatementConfidence.MEDIUM,
    )
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        ENUM(ExtractionMethod, name="extraction_method", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )

    classifier_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_status: Mapped[ReviewStatus] = mapped_column(
        ENUM(ReviewStatus, name="review_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=ReviewStatus.PENDING,
        nullable=False,
    )
    notes_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source_record = relationship("SourceRecord", backref="contextual_statements")
    source_version = relationship("SourceVersion", backref="contextual_statements")
    segment = relationship("Segment", backref="contextual_statements")
    raw_object = relationship("RawObject", backref="contextual_statements")

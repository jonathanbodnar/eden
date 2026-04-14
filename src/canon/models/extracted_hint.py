from __future__ import annotations

import uuid

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import HintType


class ExtractedHint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_hints"

    hint_type: Mapped[HintType] = mapped_column(
        ENUM(HintType, name="hint_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_start: Mapped[int | None] = mapped_column(nullable=True)
    time_end: Mapped[int | None] = mapped_column(nullable=True)
    source_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    source_statement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    extraction_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

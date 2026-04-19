from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import DatingConfidence, DateType


class SourceDate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_dates"

    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id"), nullable=False, index=True
    )
    date_type: Mapped[DateType] = mapped_column(
        ENUM(DateType, name="date_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    date_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dating_method: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dating_confidence: Mapped[DatingConfidence] = mapped_column(
        ENUM(DatingConfidence, name="dating_confidence", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=DatingConfidence.UNCERTAIN,
        nullable=False,
    )
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_record = relationship("SourceRecord", back_populates="source_dates")

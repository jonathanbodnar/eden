from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import ProvenanceStatus, RecordStatus, SourceCategory


class SourceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_records"

    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    raw_object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_objects.id"), nullable=False, index=True
    )
    canonical_title: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_category: Mapped[SourceCategory] = mapped_column(
        ENUM(SourceCategory, name="source_category", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    culture: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language_family: Mapped[str | None] = mapped_column(String(256), nullable=True)
    origin_place_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repository_institution: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provenance_status: Mapped[ProvenanceStatus] = mapped_column(
        ENUM(ProvenanceStatus, name="provenance_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=ProvenanceStatus.UNKNOWN,
        nullable=False,
    )
    authenticity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rights_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_status: Mapped[RecordStatus] = mapped_column(
        ENUM(RecordStatus, name="record_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=RecordStatus.DRAFT,
        nullable=False,
        index=True,
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    trusted_source = relationship("TrustedSource", back_populates="source_records")
    raw_object = relationship("RawObject", back_populates="source_records")
    source_dates = relationship("SourceDate", back_populates="source_record", cascade="all, delete-orphan")
    source_versions = relationship("SourceVersion", back_populates="source_record", cascade="all, delete-orphan")

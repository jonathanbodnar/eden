from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import CopyrightStatus, VersionType


class SourceVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_versions"

    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id"), nullable=False, index=True
    )
    version_type: Mapped[VersionType] = mapped_column(
        ENUM(VersionType, name="version_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(String(128), nullable=True)
    translator_editor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True)
    edition_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    copyright_status: Mapped[CopyrightStatus] = mapped_column(
        ENUM(CopyrightStatus, name="copyright_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=CopyrightStatus.UNKNOWN,
        nullable=False,
    )
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    r2_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    text_extracted: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source_record = relationship("SourceRecord", back_populates="source_versions")
    segments = relationship("Segment", back_populates="source_version", cascade="all, delete-orphan")

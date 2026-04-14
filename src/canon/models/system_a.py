"""Read-only ORM stubs for System A tables. No migrations emitted for these."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base


class SATrustedSource(Base):
    __tablename__ = "trusted_sources"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    slug: Mapped[str] = mapped_column(String(256))
    trust_tier: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean)
    is_secondary_source: Mapped[bool] = mapped_column(Boolean)


class SASourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trusted_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    raw_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    canonical_title: Mapped[str] = mapped_column(String(2048))
    source_category: Mapped[str] = mapped_column(String(64))
    culture: Mapped[str | None] = mapped_column(String(512))
    language_family: Mapped[str | None] = mapped_column(String(256))
    origin_place_name: Mapped[str | None] = mapped_column(String(512))
    provenance_status: Mapped[str] = mapped_column(String(64))
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB)


class SASourceDate(Base):
    __tablename__ = "source_dates"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    date_type: Mapped[str] = mapped_column(String(64))
    date_start: Mapped[int | None] = mapped_column(Integer)
    date_end: Mapped[int | None] = mapped_column(Integer)
    date_label: Mapped[str | None] = mapped_column(String(512))
    dating_confidence: Mapped[str] = mapped_column(String(64))


class SASourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version_type: Mapped[str] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(128))
    text_extracted: Mapped[str | None] = mapped_column(Text)


class SASegment(Base):
    __tablename__ = "segments"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    segment_type: Mapped[str] = mapped_column(String(64))
    segment_order: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SAContextualStatement(Base):
    __tablename__ = "contextual_statements"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    statement_text: Mapped[str] = mapped_column(Text)
    context_type: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(64))
    extraction_method: Mapped[str] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(64))


class SARawObject(Base):
    __tablename__ = "raw_objects"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trusted_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    external_id: Mapped[str | None] = mapped_column(String(1024))
    source_url: Mapped[str | None] = mapped_column(String(4096))
    content_type: Mapped[str | None] = mapped_column(String(256))
    r2_key: Mapped[str | None] = mapped_column(String(2048))


class SAObjectImage(Base):
    __tablename__ = "object_images"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    raw_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    trusted_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    image_url: Mapped[str] = mapped_column(Text)
    r2_key: Mapped[str | None] = mapped_column(String(2048))
    alt_text: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(256))
    image_order: Mapped[int] = mapped_column(Integer, default=0)


class SADiscoveredRecord(Base):
    __tablename__ = "discovered_records"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trusted_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title_hint: Mapped[str | None] = mapped_column(Text)
    record_url: Mapped[str | None] = mapped_column(String(4096))

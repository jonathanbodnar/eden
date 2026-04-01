from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin


class RawObject(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_objects"

    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    discovered_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovered_records.id"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    r2_key: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parser_hint: Mapped[str | None] = mapped_column(String(256), nullable=True)

    trusted_source = relationship("TrustedSource", back_populates="raw_objects")
    discovered_record = relationship("DiscoveredRecord", back_populates="raw_objects")
    source_records = relationship("SourceRecord", back_populates="raw_object")
    images = relationship("ObjectImage", back_populates="raw_object", cascade="all, delete-orphan")

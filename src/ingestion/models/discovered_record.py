from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import DiscoveredRecordStatus


class DiscoveredRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discovered_records"

    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    record_url: Mapped[str] = mapped_column(String(4096), nullable=False)
    title_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    discovery_metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[DiscoveredRecordStatus] = mapped_column(
        ENUM(DiscoveredRecordStatus, name="discovered_record_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=DiscoveredRecordStatus.NEW,
        nullable=False,
        index=True,
    )

    trusted_source = relationship("TrustedSource", back_populates="discovered_records")
    raw_objects = relationship("RawObject", back_populates="discovered_record")

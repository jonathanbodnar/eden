from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import JobStatus, JobType


class IngestionJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_jobs"

    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    job_type: Mapped[JobType] = mapped_column(
        ENUM(JobType, name="job_type", create_type=False),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        ENUM(JobStatus, name="job_status", create_type=False),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,
    )
    payload_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trusted_source = relationship("TrustedSource", back_populates="ingestion_jobs")

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import JobStatus, JobType


class QueuedJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "queued_jobs"

    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_runs.id"), nullable=True, index=True
    )
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
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    payload_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_run = relationship("SourceRun", back_populates="queued_jobs")
    trusted_source = relationship("TrustedSource", back_populates="queued_jobs")
    checkpoints = relationship("JobCheckpoint", back_populates="queued_job", cascade="all, delete-orphan")

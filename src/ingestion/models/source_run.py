from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import RunStatus, RunType


class SourceRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_runs"

    trusted_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trusted_sources.id"), nullable=False, index=True
    )
    run_type: Mapped[RunType] = mapped_column(
        ENUM(RunType, name="run_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        ENUM(RunStatus, name="run_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        default=RunStatus.QUEUED,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trusted_source = relationship("TrustedSource", back_populates="source_runs")
    queued_jobs = relationship("QueuedJob", back_populates="source_run", cascade="all, delete-orphan")

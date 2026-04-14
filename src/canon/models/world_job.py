from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import WorldJobStatus, WorldJobType


class WorldQueuedJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "world_queued_jobs"

    job_type: Mapped[WorldJobType] = mapped_column(
        ENUM(WorldJobType, name="world_job_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False, index=True,
    )
    status: Mapped[WorldJobStatus] = mapped_column(
        ENUM(WorldJobStatus, name="world_job_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False, default=WorldJobStatus.QUEUED, index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorldJobCheckpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "world_job_checkpoints"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    checkpoint_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

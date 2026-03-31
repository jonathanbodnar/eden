from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.ingestion.models.base import Base, UUIDPrimaryKeyMixin


class JobCheckpoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "job_checkpoints"

    queued_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queued_jobs.id"), nullable=False, index=True
    )
    checkpoint_type: Mapped[str] = mapped_column(String(256), nullable=False)
    cursor_value: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    external_id_last_processed: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_total_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_processed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    stage_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    checkpoint_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    queued_job = relationship("QueuedJob", back_populates="checkpoints")

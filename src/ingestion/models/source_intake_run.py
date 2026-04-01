from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.ingestion.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.ingestion.models.enums import IntakeStatus


class SourceIntakeRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_intake_runs"

    submitted_urls_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    grouped_domains_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[IntakeStatus] = mapped_column(
        ENUM(IntakeStatus, name="intake_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=IntakeStatus.PENDING,
    )
    analysis_result_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)

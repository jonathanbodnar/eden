from __future__ import annotations

import uuid

from sqlalchemy import Float, Integer, String
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import ArchiveObjectType, CanonicalType, ChangeType, UpdateTargetStatus


class ChangeEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "change_events"

    change_type: Mapped[ChangeType] = mapped_column(
        ENUM(ChangeType, name="change_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    source_object_type: Mapped[ArchiveObjectType] = mapped_column(
        ENUM(ArchiveObjectType, name="archive_object_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    source_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    affected_time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affected_time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class CanonUpdateTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canon_update_targets"

    change_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[UpdateTargetStatus] = mapped_column(
        ENUM(UpdateTargetStatus, name="update_target_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False, default=UpdateTargetStatus.PENDING,
    )

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin
from src.canon.models.enums import CanonicalType


class CanonBranch(UUIDPrimaryKeyMixin, VersionedMixin, TimestampMixin, Base):
    __tablename__ = "canon_branches"

    parent_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    branch_title: Mapped[str] = mapped_column(String(1024), nullable=False)
    branch_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternate_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

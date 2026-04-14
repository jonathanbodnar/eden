from __future__ import annotations

import uuid

from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import ArchiveObjectType, CanonicalType, SupportType


class CanonSupportLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canon_support_links"

    canonical_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    archive_object_type: Mapped[ArchiveObjectType] = mapped_column(
        ENUM(ArchiveObjectType, name="archive_object_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    archive_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    support_type: Mapped[SupportType] = mapped_column(
        ENUM(SupportType, name="support_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

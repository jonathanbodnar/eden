from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.canon.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.canon.models.enums import CanonicalType


class CanonDependency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canon_dependencies"

    parent_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    child_type: Mapped[CanonicalType] = mapped_column(
        ENUM(CanonicalType, name="canonical_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

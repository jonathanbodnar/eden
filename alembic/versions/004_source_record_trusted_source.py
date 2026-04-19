"""Add trusted_source_id to source_records for direct source tracking

Revision ID: 004
Revises: 003
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_records",
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute("""
        UPDATE source_records sr
        SET trusted_source_id = ro.trusted_source_id
        FROM raw_objects ro
        WHERE sr.raw_object_id = ro.id
    """)

    op.alter_column("source_records", "trusted_source_id", nullable=False)

    op.create_index(
        "ix_source_records_trusted_source_id",
        "source_records",
        ["trusted_source_id"],
    )
    op.create_foreign_key(
        "fk_source_records_trusted_source_id",
        "source_records",
        "trusted_sources",
        ["trusted_source_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_source_records_trusted_source_id", "source_records", type_="foreignkey")
    op.drop_index("ix_source_records_trusted_source_id", table_name="source_records")
    op.drop_column("source_records", "trusted_source_id")

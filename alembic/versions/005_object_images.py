"""Add object_images table for storing images extracted from source pages

Revision ID: 005
Revises: 004
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "object_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_objects.id"), nullable=False),
        sa.Column("trusted_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trusted_sources.id"), nullable=False),
        sa.Column("image_url", sa.Text, nullable=False),
        sa.Column("r2_key", sa.String(2048), nullable=True),
        sa.Column("alt_text", sa.Text, nullable=True),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("content_type", sa.String(256), nullable=True),
        sa.Column("byte_size", sa.Integer, nullable=True),
        sa.Column("image_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_object_images_raw_object_id", "object_images", ["raw_object_id"])
    op.create_index("ix_object_images_trusted_source_id", "object_images", ["trusted_source_id"])


def downgrade() -> None:
    op.drop_index("ix_object_images_trusted_source_id", table_name="object_images")
    op.drop_index("ix_object_images_raw_object_id", table_name="object_images")
    op.drop_table("object_images")

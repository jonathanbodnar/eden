"""Source intake: AI-assisted trusted source analysis

Revision ID: 003
Revises: 002
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    intake_status = postgresql.ENUM(
        "pending", "fetching", "analyzing", "completed", "failed",
        name="intake_status", create_type=False,
    )
    intake_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "source_intake_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("submitted_urls_jsonb", postgresql.JSONB, nullable=False),
        sa.Column("grouped_domains_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("status", intake_status, nullable=False, server_default="pending"),
        sa.Column("analysis_result_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("error_log", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_intake_runs_status", "source_intake_runs", ["status"])


def downgrade() -> None:
    op.drop_table("source_intake_runs")
    op.execute("DROP TYPE IF EXISTS intake_status")

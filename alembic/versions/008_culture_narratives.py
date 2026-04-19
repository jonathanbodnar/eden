"""Add culture_narratives and culture_event_skeletons tables for multi-pass pipeline

Revision ID: 008
Revises: 007
Create Date: 2026-04-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "culture_narratives",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_outline_id", UUID(as_uuid=True), sa.ForeignKey("story_outlines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("culture_key", sa.Text, nullable=False),
        sa.Column("culture_label", sa.Text, nullable=False),
        sa.Column("narrative_text", sa.Text, nullable=False),
        sa.Column("actors_json", JSONB, nullable=True),
        sa.Column("events_json", JSONB, nullable=True),
        sa.Column("places_json", JSONB, nullable=True),
        sa.Column("source_ids", JSONB, nullable=True),
        sa.Column("source_count", sa.Integer, server_default="0"),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("generation_version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("story_outline_id", "culture_key", name="uq_culture_narratives_outline_culture"),
    )
    op.create_index("ix_culture_narratives_outline", "culture_narratives", ["story_outline_id"])
    op.create_index("ix_culture_narratives_culture_key", "culture_narratives", ["culture_key"])

    op.create_table(
        "culture_event_skeletons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("culture_narrative_id", UUID(as_uuid=True), sa.ForeignKey("culture_narratives.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("story_outline_id", UUID(as_uuid=True), sa.ForeignKey("story_outlines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("culture_key", sa.Text, nullable=False),
        sa.Column("events_json", JSONB, nullable=False),
        sa.Column("unique_details", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_culture_event_skeletons_outline", "culture_event_skeletons", ["story_outline_id"])


def downgrade() -> None:
    op.drop_index("ix_culture_event_skeletons_outline")
    op.drop_table("culture_event_skeletons")
    op.drop_index("ix_culture_narratives_culture_key")
    op.drop_index("ix_culture_narratives_outline")
    op.drop_table("culture_narratives")

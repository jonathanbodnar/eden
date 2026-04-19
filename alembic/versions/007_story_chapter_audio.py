"""Add story_chapter_audio table for caching TTS MP3s

Revision ID: 007
Revises: 006
Create Date: 2026-04-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "story_chapter_audio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_chapter_id", UUID(as_uuid=True), sa.ForeignKey("story_chapters.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("audio_data", sa.LargeBinary, nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("voice_id", sa.String, nullable=True),
        sa.Column("model_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_story_chapter_audio_chapter", "story_chapter_audio", ["story_chapter_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_story_chapter_audio_chapter")
    op.drop_table("story_chapter_audio")

"""Deity dossier + archetype merge proposals

Revision ID: 010
Revises: 009
Create Date: 2026-04-17

Two new tables backing the audit-first archetype remerge workflow:
  - deity_dossiers: per-actor evidence packet (atomic events + canonical
    actor + earliest source + LLM characteristics)
  - archetype_merge_proposals: LLM-generated verdicts on existing
    archetypes (keep / split / reassign / merge) pending human approval
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # deity_dossiers
    # -----------------------------------------------------------------
    op.create_table(
        "deity_dossiers",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor_name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column(
            "epoch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("canonical_epochs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "canonical_actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("canonical_actors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cultures",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "event_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "actions",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "co_occurring_actors",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("earliest_source_id", UUID(as_uuid=True), nullable=True),
        sa.Column("earliest_source_title", sa.Text, nullable=True),
        sa.Column("earliest_date_start", sa.Integer, nullable=True),
        sa.Column("earliest_date_end", sa.Integer, nullable=True),
        sa.Column("earliest_date_label", sa.Text, nullable=True),
        sa.Column("dating_confidence", sa.Text, nullable=True),
        sa.Column(
            "source_passage_ids",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_passage_excerpts",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("characteristics_md", sa.Text, nullable=True),
        sa.Column(
            "current_archetype_id",
            UUID(as_uuid=True),
            sa.ForeignKey("archetype_registry.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_archetype_name", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_deity_dossiers_epoch_norm",
        "deity_dossiers",
        ["epoch_id", "normalized_name"],
        unique=True,
    )
    op.create_index(
        "ix_deity_dossiers_actor_name",
        "deity_dossiers",
        ["actor_name"],
    )
    op.create_index(
        "ix_deity_dossiers_epoch",
        "deity_dossiers",
        ["epoch_id"],
    )

    # -----------------------------------------------------------------
    # archetype_merge_proposals
    # -----------------------------------------------------------------
    op.create_table(
        "archetype_merge_proposals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "epoch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("canonical_epochs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_archetype_ids",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_archetype_names",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("proposal_kind", sa.Text, nullable=False, server_default="keep"),
        sa.Column(
            "proposed_groups",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("overall_rationale", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_note", sa.Text, nullable=True),
        sa.Column("model_name", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_archetype_merge_proposals_epoch",
        "archetype_merge_proposals",
        ["epoch_id"],
    )
    op.create_index(
        "ix_archetype_merge_proposals_status",
        "archetype_merge_proposals",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archetype_merge_proposals_status",
        table_name="archetype_merge_proposals",
    )
    op.drop_index(
        "ix_archetype_merge_proposals_epoch",
        table_name="archetype_merge_proposals",
    )
    op.drop_table("archetype_merge_proposals")

    op.drop_index("ix_deity_dossiers_epoch", table_name="deity_dossiers")
    op.drop_index("ix_deity_dossiers_actor_name", table_name="deity_dossiers")
    op.drop_index("ix_deity_dossiers_epoch_norm", table_name="deity_dossiers")
    op.drop_table("deity_dossiers")

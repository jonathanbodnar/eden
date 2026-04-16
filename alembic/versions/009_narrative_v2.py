"""Narrative Pipeline V2 — archetype registry, atomic events, event clusters

Revision ID: 009
Revises: 008
Create Date: 2026-04-16

Introduces the V2 deterministic-merge narrative pipeline tables:
  - archetype_registry: global, write-once archetype naming
  - culture_atomic_events: strict-schema events with embeddings for clustering
  - event_clusters: platform-computed merged event layer

Also extends:
  - culture_narratives: adds prose_history + fact_sheet
  - story_chapters: adds pipeline_version + archetypes_used + cluster_count

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ---------------------------------------------------------------
    # archetype_registry — global archetype name map
    # ---------------------------------------------------------------
    op.create_table(
        "archetype_registry",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("archetype_name", sa.Text, nullable=False, unique=True),
        sa.Column("role_description", sa.Text, nullable=True),
        sa.Column("entity_type", sa.Text, nullable=False, server_default="actor"),
        sa.Column("also_known_as", ARRAY(sa.Text), nullable=False,
                  server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("canonical_ids", ARRAY(UUID(as_uuid=True)), nullable=False,
                  server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("role_signature", JSONB, nullable=True),
        sa.Column("first_seen_chapter_id", UUID(as_uuid=True),
                  sa.ForeignKey("story_chapters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("first_seen_epoch_id", UUID(as_uuid=True),
                  sa.ForeignKey("canonical_epochs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_archetype_registry_aka",
        "archetype_registry",
        ["also_known_as"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_archetype_registry_entity_type",
        "archetype_registry",
        ["entity_type"],
    )

    # ---------------------------------------------------------------
    # culture_atomic_events — strict-schema events with embeddings
    # ---------------------------------------------------------------
    op.create_table(
        "culture_atomic_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("culture_narrative_id", UUID(as_uuid=True),
                  sa.ForeignKey("culture_narratives.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("story_outline_id", UUID(as_uuid=True),
                  sa.ForeignKey("story_outlines.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("culture_key", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("actors", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("verb", sa.Text, nullable=False),
        sa.Column("verb_family", sa.Text, nullable=False),
        sa.Column("objects", JSONB, nullable=True),
        sa.Column("materials", JSONB, nullable=True),
        sa.Column("place", sa.Text, nullable=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("outcome_keywords", JSONB, nullable=True),
        sa.Column("quoted_phrase", sa.Text, nullable=True),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.Column(
            "action_embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # action_embedding stays as ARRAY(Float) (double precision[]). We compute
    # cosine similarity in Python (Stage 3) — no SQL-side vector ops are needed.
    op.create_index(
        "ix_culture_atomic_events_outline",
        "culture_atomic_events",
        ["story_outline_id"],
    )
    op.create_index(
        "ix_culture_atomic_events_culture",
        "culture_atomic_events",
        ["culture_key"],
    )
    op.create_index(
        "ix_culture_atomic_events_verb_family",
        "culture_atomic_events",
        ["verb_family"],
    )

    # ---------------------------------------------------------------
    # event_clusters — platform-computed merged event layer
    # ---------------------------------------------------------------
    op.create_table(
        "event_clusters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_outline_id", UUID(as_uuid=True),
                  sa.ForeignKey("story_outlines.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("cluster_key", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("primary_archetype_name", sa.Text, nullable=False),
        sa.Column("archetype_registry_id", UUID(as_uuid=True),
                  sa.ForeignKey("archetype_registry.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("contributing_event_ids", ARRAY(UUID(as_uuid=True)), nullable=False,
                  server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("contributing_cultures", JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("canonical_verb", sa.Text, nullable=False),
        sa.Column("canonical_outcome", sa.Text, nullable=False),
        sa.Column("verb_family", sa.Text, nullable=False),
        sa.Column("materials", JSONB, nullable=True),
        sa.Column("vivid_details", JSONB, nullable=True),
        sa.Column("source_quotes", JSONB, nullable=True),
        sa.Column("age_rank_of_oldest", sa.Integer, nullable=False),
        sa.Column("retention_score", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_event_clusters_outline_seq",
        "event_clusters",
        ["story_outline_id", "seq"],
    )
    op.create_index(
        "ix_event_clusters_archetype",
        "event_clusters",
        ["archetype_registry_id"],
    )

    # ---------------------------------------------------------------
    # culture_narratives: add prose_history + fact_sheet
    # ---------------------------------------------------------------
    op.add_column(
        "culture_narratives",
        sa.Column("prose_history", sa.Text, nullable=True),
    )
    op.add_column(
        "culture_narratives",
        sa.Column("fact_sheet", JSONB, nullable=True),
    )

    # ---------------------------------------------------------------
    # story_chapters: add V2 metadata
    # ---------------------------------------------------------------
    op.add_column(
        "story_chapters",
        sa.Column("pipeline_version", sa.Text, nullable=False,
                  server_default="v1"),
    )
    op.add_column(
        "story_chapters",
        sa.Column("cluster_count", sa.Integer, nullable=True),
    )
    op.add_column(
        "story_chapters",
        sa.Column("archetypes_used", ARRAY(sa.Text), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("story_chapters", "archetypes_used")
    op.drop_column("story_chapters", "cluster_count")
    op.drop_column("story_chapters", "pipeline_version")

    op.drop_column("culture_narratives", "fact_sheet")
    op.drop_column("culture_narratives", "prose_history")

    op.drop_index("ix_event_clusters_archetype", table_name="event_clusters")
    op.drop_index("ix_event_clusters_outline_seq", table_name="event_clusters")
    op.drop_table("event_clusters")

    op.drop_index("ix_culture_atomic_events_verb_family", table_name="culture_atomic_events")
    op.drop_index("ix_culture_atomic_events_culture", table_name="culture_atomic_events")
    op.drop_index("ix_culture_atomic_events_outline", table_name="culture_atomic_events")
    op.drop_table("culture_atomic_events")

    op.drop_index("ix_archetype_registry_entity_type", table_name="archetype_registry")
    op.drop_index("ix_archetype_registry_aka", table_name="archetype_registry")
    op.drop_table("archetype_registry")

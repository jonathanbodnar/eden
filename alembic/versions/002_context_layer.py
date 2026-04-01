"""Context layer: contextual_statements table, new enums, alter trusted_sources

Revision ID: 002
Revises: 001
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New enum types ---
    context_type = postgresql.ENUM(
        "descriptive", "comparative", "scholarly_consensus", "scholarly_debate",
        "functional_hypothesis", "uncertain",
        name="context_type", create_type=False,
    )
    context_type.create(op.get_bind(), checkfirst=True)

    extraction_method = postgresql.ENUM(
        "rules_based", "llm_classified", "hybrid", "manual",
        name="extraction_method", create_type=False,
    )
    extraction_method.create(op.get_bind(), checkfirst=True)

    statement_confidence = postgresql.ENUM(
        "high", "medium", "low", "uncertain",
        name="statement_confidence", create_type=False,
    )
    statement_confidence.create(op.get_bind(), checkfirst=True)

    # --- Add extract_context to job_type enum ---
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'extract_context'")

    # --- Add is_secondary_source to trusted_sources ---
    op.add_column(
        "trusted_sources",
        sa.Column("is_secondary_source", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )

    # --- contextual_statements table ---
    op.create_table(
        "contextual_statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_versions.id"), nullable=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("segments.id"), nullable=True),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_objects.id"), nullable=True),
        sa.Column("statement_text", sa.Text, nullable=False),
        sa.Column("context_type", context_type, nullable=False),
        sa.Column("confidence", statement_confidence, nullable=False, server_default="medium"),
        sa.Column("extraction_method", extraction_method, nullable=False),
        sa.Column("classifier_model", sa.String(256), nullable=True),
        sa.Column("classifier_version", sa.String(256), nullable=True),
        sa.Column("source_reference", sa.Text, nullable=True),
        sa.Column("supporting_quote", sa.Text, nullable=True),
        sa.Column(
            "review_status",
            postgresql.ENUM(
                "pending", "approved", "rejected", "needs_review",
                name="review_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("notes_jsonb", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_contextual_statements_source_record", "contextual_statements", ["source_record_id"])
    op.create_index("ix_contextual_statements_segment", "contextual_statements", ["segment_id"])
    op.create_index("ix_contextual_statements_context_type", "contextual_statements", ["context_type"])
    op.create_index("ix_contextual_statements_review_status", "contextual_statements", ["review_status"])
    op.create_index("ix_contextual_statements_source_version", "contextual_statements", ["source_version_id"])


def downgrade() -> None:
    op.drop_table("contextual_statements")
    op.drop_column("trusted_sources", "is_secondary_source")

    for enum_name in ["statement_confidence", "extraction_method", "context_type"]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

"""Add classification_kind to archetype_registry for primary vs class archetypes

Revision ID: 011
Revises: 010
Create Date: 2026-04-17

An archetype can be either:
  - 'primary' (default): the deity's specific functional role (e.g., "The
    Feathered Serpent", "The Flood Hero", "The Chaos-Slaying Champion").
    A deity belongs to exactly one primary archetype. Event chapters
    narrate around primary archetypes.
  - 'class': a broader collective / plural / taxonomic grouping (e.g.,
    "The Elohim", "The Anunnaki", "The Devas", "The Shining Ones",
    "The Titan Generation"). A deity can belong to many classes.

Distinct from also_known_as which already supports multi-membership at
the row level — the column tells us whether overlap across rows is
expected (class) or should be prevented (primary).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "archetype_registry",
        sa.Column(
            "classification_kind",
            sa.Text,
            nullable=False,
            server_default="primary",
        ),
    )
    op.create_check_constraint(
        "ck_archetype_registry_classification_kind",
        "archetype_registry",
        "classification_kind IN ('primary', 'class')",
    )
    op.create_index(
        "ix_archetype_registry_classification_kind",
        "archetype_registry",
        ["classification_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archetype_registry_classification_kind",
        table_name="archetype_registry",
    )
    op.drop_constraint(
        "ck_archetype_registry_classification_kind",
        "archetype_registry",
        type_="check",
    )
    op.drop_column("archetype_registry", "classification_kind")

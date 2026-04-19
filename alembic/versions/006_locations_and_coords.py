"""Add latitude/longitude to source_records for location/gazetteer data

Revision ID: 006
Revises: 005
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_records", sa.Column("latitude", sa.Float, nullable=True))
    op.add_column("source_records", sa.Column("longitude", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("source_records", "longitude")
    op.drop_column("source_records", "latitude")

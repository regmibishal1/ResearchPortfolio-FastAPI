"""Add match_details JSONB column to worldcup.brackets.

Carries per-round per-match scoreline records: predicted score from the
Poisson xG solver, plus actual score / went_to_penalties / winner for
knockout matches that have already been played. Nullable so older
snapshots pushed before this migration keep working.

Revision ID: 20260630_0002
Revises: 20260628_0001
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "20260630_0002"
down_revision: Union[str, None] = "20260628_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "worldcup"


def upgrade() -> None:
    op.add_column(
        "brackets",
        sa.Column("match_details", JSONB, nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("brackets", "match_details", schema=SCHEMA)

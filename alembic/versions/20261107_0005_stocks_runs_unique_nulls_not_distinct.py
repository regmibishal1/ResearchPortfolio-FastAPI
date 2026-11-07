"""Treat NULL labels as equal in the stocks runs uniqueness constraint.

The same fix as 20260705_0004, for stocks.runs: with an ordinary unique
constraint the ingest upsert never conflicted for unlabeled snapshots, so
every re-push of a date inserted another full run. Collapse the duplicates
that accumulated, keeping the most recent run of each group, then rebuild
the constraint with NULLS NOT DISTINCT (Postgres 15+).

Revision ID: 20261107_0005
Revises: 20260705_0004
Create Date: 2026-11-07
"""

from alembic import op

revision = "20261107_0005"
down_revision = "20260705_0004"
branch_labels = None
depends_on = None

SCHEMA = "stocks"
CONSTRAINT = "uq_stocks_runs_date_label"


def upgrade() -> None:
    # Keep the newest row per (as_of_date, label) group, NULL labels
    # included. Sectors, companies and track record follow via ON DELETE
    # CASCADE.
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.runs r
        USING {SCHEMA}.runs newer
        WHERE r.as_of_date = newer.as_of_date
          AND r.label IS NOT DISTINCT FROM newer.label
          AND (newer.run_timestamp_utc, newer.id) > (r.run_timestamp_utc, r.id)
        """
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs DROP CONSTRAINT {CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs ADD CONSTRAINT {CONSTRAINT} "
        "UNIQUE NULLS NOT DISTINCT (as_of_date, label)"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs DROP CONSTRAINT {CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs ADD CONSTRAINT {CONSTRAINT} "
        "UNIQUE (as_of_date, label)"
    )

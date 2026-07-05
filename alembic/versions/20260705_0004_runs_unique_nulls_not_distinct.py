"""Treat NULL labels as equal in the runs uniqueness constraint.

Postgres considers NULLs distinct in ordinary unique constraints, so the
ingest upsert never conflicted for unlabeled (canonical) snapshots and
every push inserted a duplicate row for the same tournament and date.
Rebuild the constraint with NULLS NOT DISTINCT (Postgres 15+) after
collapsing any duplicates that already accumulated, keeping the most
recent run of each group.

Revision ID: 20260705_0004
Revises: 20260705_0003
Create Date: 2026-07-05
"""

from alembic import op

revision = "20260705_0004"
down_revision = "20260705_0003"
branch_labels = None
depends_on = None

SCHEMA = "worldcup"
CONSTRAINT = "uq_worldcup_runs_tournament_date_label"


def upgrade() -> None:
    # Collapse existing duplicates: keep the newest row per
    # (tournament_key, as_of_date, label) group, NULL labels included.
    # Satellite rows follow via ON DELETE CASCADE.
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.runs r
        USING {SCHEMA}.runs newer
        WHERE r.tournament_key = newer.tournament_key
          AND r.as_of_date = newer.as_of_date
          AND r.label IS NOT DISTINCT FROM newer.label
          AND (newer.run_timestamp_utc, newer.id) > (r.run_timestamp_utc, r.id)
        """
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs DROP CONSTRAINT {CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs ADD CONSTRAINT {CONSTRAINT} "
        "UNIQUE NULLS NOT DISTINCT (tournament_key, as_of_date, label)"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs DROP CONSTRAINT {CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.runs ADD CONSTRAINT {CONSTRAINT} "
        "UNIQUE (tournament_key, as_of_date, label)"
    )

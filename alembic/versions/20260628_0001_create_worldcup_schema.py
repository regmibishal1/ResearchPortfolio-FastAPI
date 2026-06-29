"""Create the worldcup schema, roles, tables, and grants.

This migration:
  * creates the `worldcup` schema (isolated from public/auth)
  * creates two least-privilege roles:
      - `worldcup_writer`  : INSERT / UPDATE / DELETE / SELECT
      - `worldcup_reader`  : SELECT only
  * creates four tables (runs, team_probabilities, brackets, played_matches)
  * grants schema + table privileges to those roles

Role creation requires a privileged DB user. The runtime FastAPI never
connects with that privileged role — it connects with worldcup_reader.

Revision ID: 20260628_0001
Revises:
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "20260628_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "worldcup"


def upgrade() -> None:
    # ---- 1. Schema ---------------------------------------------------------
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ---- 2. Roles (idempotent via pg_roles check) --------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worldcup_writer') THEN
                CREATE ROLE worldcup_writer NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worldcup_reader') THEN
                CREATE ROLE worldcup_reader NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    # ---- 3. Tables ---------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tournament_key", sa.String(length=16), nullable=False, server_default="2026"),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("n_simulations", sa.Integer(), nullable=False),
        sa.Column("n_played_matches_locked", sa.Integer(), nullable=False),
        sa.Column(
            "run_timestamp_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint(
            "tournament_key", "as_of_date", "label",
            name="uq_worldcup_runs_tournament_date_label",
        ),
        sa.CheckConstraint("n_simulations > 0", name="ck_worldcup_runs_n_simulations_pos"),
        sa.CheckConstraint("n_played_matches_locked >= 0", name="ck_worldcup_runs_n_played_nonneg"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_worldcup_runs_tournament_as_of_date",
        "runs",
        ["tournament_key", "as_of_date"],
        schema=SCHEMA,
    )

    op.create_table(
        "team_probabilities",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("winner_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("final_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("sf_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("qf_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("r16_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("r32_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("elo", sa.Numeric(7, 1), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "team", name="pk_worldcup_team_probabilities"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_worldcup_team_probabilities_team_run",
        "team_probabilities",
        ["team", "run_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "brackets",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("group_winners", JSONB, nullable=False),
        sa.Column("best_thirds", JSONB, nullable=False),
        sa.Column("r32", JSONB, nullable=False),
        sa.Column("r16", JSONB, nullable=False),
        sa.Column("qf", JSONB, nullable=False),
        sa.Column("sf", JSONB, nullable=False),
        sa.Column("final_pair", JSONB, nullable=False),
        sa.Column("champion", sa.String(length=64), nullable=False),
        schema=SCHEMA,
    )

    op.create_table(
        "played_matches",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_date", sa.Date(), nullable=False),
        sa.Column("home_team", sa.String(length=64), nullable=False),
        sa.Column("away_team", sa.String(length=64), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=2), nullable=True),
        sa.PrimaryKeyConstraint(
            "run_id", "match_date", "home_team", "away_team",
            name="pk_worldcup_played_matches",
        ),
        sa.CheckConstraint("home_score >= 0", name="ck_worldcup_played_home_score_nonneg"),
        sa.CheckConstraint("away_score >= 0", name="ck_worldcup_played_away_score_nonneg"),
        schema=SCHEMA,
    )

    # ---- 4. Grants ---------------------------------------------------------
    # Schema usage: both roles need it to address objects inside.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO worldcup_writer, worldcup_reader")

    # Writer: full DML on every existing and future table in the schema.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
        "TO worldcup_writer"
    )
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO worldcup_writer"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO worldcup_writer"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT USAGE, SELECT ON SEQUENCES TO worldcup_writer"
    )

    # Reader: SELECT only, on existing and future tables.
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO worldcup_reader")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT SELECT ON TABLES TO worldcup_reader"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.played_matches CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.brackets CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.team_probabilities CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.runs CASCADE")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    # Roles intentionally NOT dropped — they may be referenced by other grants
    # or owned by other objects. Drop manually if you really mean to.

"""Create the stocks schema, roles, tables, and grants.

This migration:
  * creates the `stocks` schema (isolated from public/auth/worldcup)
  * creates two least-privilege roles:
      - `stocks_writer`  : INSERT / UPDATE / DELETE / SELECT
      - `stocks_reader`  : SELECT only
  * creates four tables (runs, sectors, companies, track_record)
  * grants schema + table privileges to those roles

Role creation requires a privileged DB user. The runtime FastAPI never
connects with that privileged role, it connects with stocks_reader.

Revision ID: 20260705_0003
Revises: 20260630_0002
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "20260705_0003"
down_revision: Union[str, None] = "20260630_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "stocks"


def upgrade() -> None:
    # ---- 1. Schema ---------------------------------------------------------
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ---- 2. Roles (idempotent via pg_roles check) --------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stocks_writer') THEN
                CREATE ROLE stocks_writer NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stocks_reader') THEN
                CREATE ROLE stocks_reader NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    # ---- 3. Tables ---------------------------------------------------------
    # One row per analysis snapshot. Headline evaluation numbers live in the
    # metrics JSONB so the report format can evolve without a migration.
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("n_events", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "run_timestamp_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("as_of_date", "label", name="uq_stocks_runs_date_label"),
        sa.CheckConstraint("universe_size > 0", name="ck_stocks_runs_universe_pos"),
        sa.CheckConstraint("n_events >= 0", name="ck_stocks_runs_n_events_nonneg"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stocks_runs_as_of_date",
        "runs",
        ["as_of_date"],
        schema=SCHEMA,
    )

    # Per-sector aggregates for a run, the source for the sector heatmap.
    op.create_table(
        "sectors",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sector", sa.String(length=16), nullable=False),
        sa.Column("sector_name", sa.String(length=64), nullable=False),
        sa.Column("n_names", sa.Integer(), nullable=False),
        sa.Column("mean_sue", sa.Numeric(12, 5), nullable=True),
        sa.Column("mean_predicted_vol", sa.Numeric(12, 5), nullable=True),
        sa.Column("mean_exret_63", sa.Numeric(12, 5), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "sector", name="pk_stocks_sectors"),
        sa.CheckConstraint("n_names >= 0", name="ck_stocks_sectors_n_names_nonneg"),
        schema=SCHEMA,
    )

    # Per-company latest signal for a run, powering the company table/detail.
    op.create_table(
        "companies",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("sector", sa.String(length=16), nullable=False),
        sa.Column("company_name", sa.String(length=128), nullable=True),
        sa.Column("filed", sa.Date(), nullable=True),
        sa.Column("sue", sa.Numeric(12, 5), nullable=True),
        sa.Column("rev_sue", sa.Numeric(12, 5), nullable=True),
        sa.Column("ni_sue", sa.Numeric(12, 5), nullable=True),
        sa.Column("lag_days", sa.Integer(), nullable=True),
        sa.Column("pre_vol", sa.Numeric(12, 5), nullable=True),
        sa.Column("predicted_vol", sa.Numeric(12, 5), nullable=True),
        sa.Column("exret_63", sa.Numeric(12, 5), nullable=True),
        sa.Column("sue_quintile", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "ticker", name="pk_stocks_companies"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stocks_companies_run_sector",
        "companies",
        ["run_id", "sector"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stocks_companies_ticker",
        "companies",
        ["ticker"],
        schema=SCHEMA,
    )

    # Realized walk-forward track record for a run, the honest prediction-vs
    # -outcome series shown on the site (per period IC and long-short return).
    op.create_table(
        "track_record",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_label", sa.String(length=16), nullable=False),
        sa.Column("ic", sa.Numeric(12, 5), nullable=True),
        sa.Column("long_short_ret", sa.Numeric(12, 5), nullable=True),
        sa.Column("n", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "period_label", name="pk_stocks_track_record"),
        schema=SCHEMA,
    )

    # ---- 4. Grants ---------------------------------------------------------
    # Schema usage: both roles need it to address objects inside.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO stocks_writer, stocks_reader")

    # Writer: full DML on every existing and future table in the schema.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
        "TO stocks_writer"
    )
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO stocks_writer"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO stocks_writer"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT USAGE, SELECT ON SEQUENCES TO stocks_writer"
    )

    # Reader: SELECT only, on existing and future tables.
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO stocks_reader")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        "GRANT SELECT ON TABLES TO stocks_reader"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.track_record CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.companies CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.sectors CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.runs CASCADE")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    # Roles intentionally NOT dropped, they may be referenced by other grants
    # or owned by other objects. Drop manually if you really mean to.

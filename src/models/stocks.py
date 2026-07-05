"""ORM models for the `stocks` schema.

Each analysis snapshot produces one row in `stocks.runs` plus satellite rows
for the sector aggregates, per-company signals, and the realized walk-forward
track record. Signal values are stored as NUMERIC so they round-trip exactly;
the headline evaluation numbers live in the runs.metrics JSONB so the report
format can change without a migration.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

STOCKS_SCHEMA = "stocks"


class StocksRun(Base):
    """One row per analysis snapshot."""

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("as_of_date", "label", name="uq_stocks_runs_date_label"),
        Index("ix_stocks_runs_as_of_date", "as_of_date"),
        CheckConstraint("universe_size > 0", name="ck_stocks_runs_universe_pos"),
        CheckConstraint("n_events >= 0", name="ck_stocks_runs_n_events_nonneg"),
        {"schema": STOCKS_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    # Headline walk-forward evaluation numbers (ic_mean, ic_t, ls_mean_qtr,
    # ls_sharpe, ret_auc, ret_brier, vol_r2_model, vol_r2_persistence, ...).
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    sectors: Mapped[list["StocksSector"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    companies: Mapped[list["StocksCompany"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    track_record: Mapped[list["StocksTrackRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class StocksSector(Base):
    """Per-sector aggregates for a run, the source for the sector heatmap."""

    __tablename__ = "sectors"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "sector", name="pk_stocks_sectors"),
        CheckConstraint("n_names >= 0", name="ck_stocks_sectors_n_names_nonneg"),
        {"schema": STOCKS_SCHEMA},
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{STOCKS_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sector: Mapped[str] = mapped_column(String(16), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    n_names: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_sue: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    mean_predicted_vol: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    mean_exret_63: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)

    run: Mapped["StocksRun"] = relationship(back_populates="sectors")


class StocksCompany(Base):
    """Per-company latest signal for a run."""

    __tablename__ = "companies"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "ticker", name="pk_stocks_companies"),
        Index("ix_stocks_companies_run_sector", "run_id", "sector"),
        Index("ix_stocks_companies_ticker", "ticker"),
        {"schema": STOCKS_SCHEMA},
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{STOCKS_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    sector: Mapped[str] = mapped_column(String(16), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filed: Mapped[date | None] = mapped_column(Date, nullable=True)
    sue: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    rev_sue: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    ni_sue: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pre_vol: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    predicted_vol: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    exret_63: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    sue_quintile: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    run: Mapped["StocksRun"] = relationship(back_populates="companies")


class StocksTrackRecord(Base):
    """Realized walk-forward track record for a run (per-period IC and
    long-short return), the honest prediction-vs-outcome series.
    """

    __tablename__ = "track_record"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "period_label", name="pk_stocks_track_record"),
        {"schema": STOCKS_SCHEMA},
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{STOCKS_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_label: Mapped[str] = mapped_column(String(16), nullable=False)
    ic: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    long_short_ret: Mapped[float | None] = mapped_column(Numeric(12, 5), nullable=True)
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped["StocksRun"] = relationship(back_populates="track_record")

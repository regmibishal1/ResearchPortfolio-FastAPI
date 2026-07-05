"""EDGAR fundamentals signal endpoints.

All endpoints read from the `stocks` schema in Postgres. They are read-only
and authenticate as the `stocks_reader` role. Writes are the responsibility of
the ingestion script in the edgar-signals analysis repo.

Endpoints
---------
GET /stocks/latest             Latest snapshot metadata, headline metrics, sector heatmap
GET /stocks/companies          Per-company signals for the latest snapshot
GET /stocks/company/{ticker}   One company's latest signal plus its history across snapshots
GET /stocks/track-record       Realized walk-forward track record for the latest snapshot
GET /stocks/history            A single run-level metric across every snapshot
"""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_stocks_db
from src.models import StocksCompany, StocksRun, StocksSector, StocksTrackRecord

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------
class RunMeta(BaseModel):
    id: int
    as_of_date: date
    label: str | None
    universe_size: int
    n_events: int
    start_date: date
    end_date: date
    run_timestamp_utc: datetime
    metrics: dict


class SectorRow(BaseModel):
    sector: str
    sector_name: str
    n_names: int
    mean_sue: float | None
    mean_predicted_vol: float | None
    mean_exret_63: float | None


class LatestResponse(BaseModel):
    run: RunMeta
    sectors: list[SectorRow]


class CompanyRow(BaseModel):
    ticker: str
    sector: str
    company_name: str | None
    filed: date | None
    sue: float | None
    rev_sue: float | None
    ni_sue: float | None
    lag_days: int | None
    pre_vol: float | None
    predicted_vol: float | None
    exret_63: float | None
    sue_quintile: int | None


class CompaniesResponse(BaseModel):
    run: RunMeta
    companies: list[CompanyRow]


class CompanyHistoryPoint(BaseModel):
    as_of_date: date
    label: str | None
    sue: float | None
    predicted_vol: float | None
    exret_63: float | None


class CompanyDetailResponse(BaseModel):
    run: RunMeta
    latest: CompanyRow
    history: list[CompanyHistoryPoint]


class TrackRecordPoint(BaseModel):
    period_label: str
    ic: float | None
    long_short_ret: float | None
    n: int | None


class TrackRecordResponse(BaseModel):
    run: RunMeta
    points: list[TrackRecordPoint]


class MetricPoint(BaseModel):
    as_of_date: date
    label: str | None
    value: float | None


class HistoryResponse(BaseModel):
    metric: str
    points: list[MetricPoint]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _latest_run(db: AsyncSession, as_of_date: date | None = None) -> StocksRun:
    """Return the most recent snapshot, optionally pinned to a specific date.
    Ordered by as_of_date then run_timestamp_utc so multiple same-day labels
    resolve to the chronologically last write.
    """
    query = select(StocksRun)
    if as_of_date is not None:
        query = query.where(StocksRun.as_of_date == as_of_date)
    result = await db.execute(
        query.order_by(
            StocksRun.as_of_date.desc(),
            StocksRun.run_timestamp_utc.desc(),
        ).limit(1)
    )
    run = result.scalar_one_or_none()
    if run is None:
        detail = "No stocks snapshots found"
        if as_of_date is not None:
            detail = f"{detail} on {as_of_date.isoformat()}"
        raise HTTPException(status_code=404, detail=detail)
    return run


def _num(value) -> float | None:
    return None if value is None else float(value)


def _run_to_meta(run: StocksRun) -> RunMeta:
    return RunMeta(
        id=run.id,
        as_of_date=run.as_of_date,
        label=run.label,
        universe_size=run.universe_size,
        n_events=run.n_events,
        start_date=run.start_date,
        end_date=run.end_date,
        run_timestamp_utc=run.run_timestamp_utc,
        metrics=run.metrics or {},
    )


def _company_to_row(c: StocksCompany) -> CompanyRow:
    return CompanyRow(
        ticker=c.ticker,
        sector=c.sector,
        company_name=c.company_name,
        filed=c.filed,
        sue=_num(c.sue),
        rev_sue=_num(c.rev_sue),
        ni_sue=_num(c.ni_sue),
        lag_days=c.lag_days,
        pre_vol=_num(c.pre_vol),
        predicted_vol=_num(c.predicted_vol),
        exret_63=_num(c.exret_63),
        sue_quintile=c.sue_quintile,
    )


# Run-level metrics exposed by /history. Restricting to a known set keeps the
# JSONB key out of any dynamic SQL and rejects unknown metric names cleanly.
HISTORY_METRICS = {
    "ic_mean",
    "ic_t",
    "ls_mean_qtr",
    "ls_sharpe",
    "ret_auc",
    "ret_brier",
    "vol_r2_model",
    "vol_r2_persistence",
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/latest", response_model=LatestResponse)
async def get_latest(
    as_of_date: date | None = Query(
        default=None, description="Pin to a specific snapshot date instead of the latest"
    ),
    db: AsyncSession = Depends(get_stocks_db),
):
    """Latest snapshot metadata, headline metrics, and the sector heatmap."""
    run = await _latest_run(db, as_of_date)

    result = await db.execute(
        select(StocksSector)
        .where(StocksSector.run_id == run.id)
        .order_by(StocksSector.sector)
    )
    sectors = [
        SectorRow(
            sector=s.sector,
            sector_name=s.sector_name,
            n_names=s.n_names,
            mean_sue=_num(s.mean_sue),
            mean_predicted_vol=_num(s.mean_predicted_vol),
            mean_exret_63=_num(s.mean_exret_63),
        )
        for s in result.scalars().all()
    ]
    return LatestResponse(run=_run_to_meta(run), sectors=sectors)


@router.get("/companies", response_model=CompaniesResponse)
async def get_companies(
    sector: str | None = Query(default=None, description="Filter to one sector ETF code"),
    limit: int = Query(default=200, ge=1, le=1000),
    as_of_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_stocks_db),
):
    """Per-company signals for the latest snapshot (optionally one sector)."""
    run = await _latest_run(db, as_of_date)

    query = select(StocksCompany).where(StocksCompany.run_id == run.id)
    if sector:
        query = query.where(StocksCompany.sector == sector)
    query = query.order_by(StocksCompany.sue.desc().nullslast()).limit(limit)

    result = await db.execute(query)
    companies = [_company_to_row(c) for c in result.scalars().all()]
    return CompaniesResponse(run=_run_to_meta(run), companies=companies)


@router.get("/company/{ticker}", response_model=CompanyDetailResponse)
async def get_company(
    ticker: str,
    db: AsyncSession = Depends(get_stocks_db),
):
    """One company's latest signal plus its history across every snapshot."""
    ticker = ticker.upper()
    run = await _latest_run(db)

    result = await db.execute(
        select(StocksCompany).where(
            StocksCompany.run_id == run.id,
            StocksCompany.ticker == ticker,
        )
    )
    latest = result.scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail=f"No signal for {ticker!r} in the latest snapshot",
        )

    # History across snapshots: join companies to runs, ordered chronologically.
    sql = text(
        """
        SELECT
            r.as_of_date,
            r.label,
            c.sue::float          AS sue,
            c.predicted_vol::float AS predicted_vol,
            c.exret_63::float     AS exret_63
        FROM stocks.companies c
        JOIN stocks.runs r ON r.id = c.run_id
        WHERE c.ticker = :ticker
        ORDER BY r.as_of_date, r.run_timestamp_utc
        """
    )
    rows = await db.execute(sql, {"ticker": ticker})
    history = [
        CompanyHistoryPoint(
            as_of_date=row["as_of_date"],
            label=row["label"],
            sue=row["sue"],
            predicted_vol=row["predicted_vol"],
            exret_63=row["exret_63"],
        )
        for row in rows.mappings()
    ]
    return CompanyDetailResponse(
        run=_run_to_meta(run),
        latest=_company_to_row(latest),
        history=history,
    )


@router.get("/track-record", response_model=TrackRecordResponse)
async def get_track_record(
    as_of_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_stocks_db),
):
    """Realized walk-forward track record for the latest snapshot."""
    run = await _latest_run(db, as_of_date)

    result = await db.execute(
        select(StocksTrackRecord)
        .where(StocksTrackRecord.run_id == run.id)
        .order_by(StocksTrackRecord.period_label)
    )
    points = [
        TrackRecordPoint(
            period_label=p.period_label,
            ic=_num(p.ic),
            long_short_ret=_num(p.long_short_ret),
            n=p.n,
        )
        for p in result.scalars().all()
    ]
    return TrackRecordResponse(run=_run_to_meta(run), points=points)


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    metric: str = Query(default="ic_t", description="Run-level metric key"),
    db: AsyncSession = Depends(get_stocks_db),
):
    """A single run-level metric across every snapshot, for a trend chart."""
    if metric not in HISTORY_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric {metric!r}; valid keys: {sorted(HISTORY_METRICS)}",
        )

    # metric is validated against a fixed allowlist above, so the ->> key is
    # bound as a parameter and never interpolated from raw user input.
    sql = text(
        """
        SELECT as_of_date, label, (metrics ->> :metric)::float AS value
        FROM stocks.runs
        ORDER BY as_of_date, run_timestamp_utc
        """
    )
    rows = await db.execute(sql, {"metric": metric})
    points = [
        MetricPoint(as_of_date=row["as_of_date"], label=row["label"], value=row["value"])
        for row in rows.mappings()
    ]
    return HistoryResponse(metric=metric, points=points)

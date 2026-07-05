"""Admin-only write endpoints for the stocks schema.

Split from the read-side `stocks` router so the public read endpoints can stay
on the `has_api_key` gate while ingest is restricted to the admin bearer token,
never exposed to the UI.

Endpoints
---------
POST /stocks/ingest    push an analysis snapshot from the edgar-signals pipeline
"""

import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_stocks_writer_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------
class IngestRunMeta(BaseModel):
    as_of_date: date
    label: str | None = None
    universe_size: int = Field(gt=0)
    n_events: int = Field(ge=0)
    start_date: date
    end_date: date
    run_timestamp_utc: datetime
    # Headline walk-forward evaluation numbers. Free-form so the report format
    # can evolve without a migration; stored in the runs.metrics JSONB.
    metrics: dict = {}
    metadata: dict = {}


class IngestSector(BaseModel):
    sector: str = Field(min_length=1, max_length=16)
    sector_name: str = Field(min_length=1, max_length=64)
    n_names: int = Field(ge=0)
    mean_sue: float | None = None
    mean_predicted_vol: float | None = None
    mean_exret_63: float | None = None


class IngestCompany(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    sector: str = Field(min_length=1, max_length=16)
    company_name: str | None = Field(default=None, max_length=128)
    filed: date | None = None
    sue: float | None = None
    rev_sue: float | None = None
    ni_sue: float | None = None
    lag_days: int | None = None
    pre_vol: float | None = None
    predicted_vol: float | None = None
    exret_63: float | None = None
    sue_quintile: int | None = Field(default=None, ge=1, le=5)


class IngestTrackRecord(BaseModel):
    period_label: str = Field(min_length=1, max_length=16)
    ic: float | None = None
    long_short_ret: float | None = None
    n: int | None = None


class IngestPayload(BaseModel):
    meta: IngestRunMeta
    sectors: list[IngestSector] = []
    companies: list[IngestCompany] = Field(min_length=1)
    track_record: list[IngestTrackRecord] = []


class IngestResponse(BaseModel):
    run_id: int
    rows_written: dict[str, int]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@router.post("/ingest", response_model=IngestResponse)
async def ingest_snapshot(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_stocks_writer_db),
):
    """Push an analysis snapshot into the stocks schema.

    Idempotent: re-posting the same (as_of_date, label) upserts the run row
    and replaces every satellite row inside one transaction.
    """
    logger.info(
        "stocks ingest as_of=%s label=%s universe=%d companies=%d sectors=%d",
        payload.meta.as_of_date.isoformat(),
        payload.meta.label,
        payload.meta.universe_size,
        len(payload.companies),
        len(payload.sectors),
    )

    async with db.begin():
        # --- 1. Upsert the run row ---
        result = await db.execute(
            text(
                """
                INSERT INTO stocks.runs
                    (as_of_date, label, universe_size, n_events,
                     start_date, end_date, run_timestamp_utc, metrics, metadata)
                VALUES (:as_of, :label, :usize, :nevents,
                        :start, :end, :ts,
                        CAST(:metrics AS jsonb), CAST(:meta AS jsonb))
                ON CONFLICT (as_of_date, label) DO UPDATE
                    SET universe_size     = EXCLUDED.universe_size,
                        n_events          = EXCLUDED.n_events,
                        start_date        = EXCLUDED.start_date,
                        end_date          = EXCLUDED.end_date,
                        run_timestamp_utc = EXCLUDED.run_timestamp_utc,
                        metrics           = EXCLUDED.metrics,
                        metadata          = EXCLUDED.metadata
                RETURNING id
                """
            ),
            {
                "as_of": payload.meta.as_of_date,
                "label": payload.meta.label,
                "usize": payload.meta.universe_size,
                "nevents": payload.meta.n_events,
                "start": payload.meta.start_date,
                "end": payload.meta.end_date,
                "ts": payload.meta.run_timestamp_utc,
                "metrics": _json(payload.meta.metrics),
                "meta": _json(payload.meta.metadata),
            },
        )
        run_id: int = result.scalar_one()

        # --- 2. Replace satellite tables for this run ---
        for table in ("sectors", "companies", "track_record"):
            await db.execute(
                text(f"DELETE FROM stocks.{table} WHERE run_id = :rid"),
                {"rid": run_id},
            )

        # --- 3. Sectors ---
        if payload.sectors:
            sector_rows = [
                {
                    "rid": run_id,
                    "sector": s.sector,
                    "name": s.sector_name,
                    "n": s.n_names,
                    "sue": s.mean_sue,
                    "pvol": s.mean_predicted_vol,
                    "exret": s.mean_exret_63,
                }
                for s in payload.sectors
            ]
            await db.execute(
                text(
                    """
                    INSERT INTO stocks.sectors
                        (run_id, sector, sector_name, n_names,
                         mean_sue, mean_predicted_vol, mean_exret_63)
                    VALUES (:rid, :sector, :name, :n, :sue, :pvol, :exret)
                    """
                ),
                sector_rows,
            )

        # --- 4. Companies ---
        company_rows = [
            {
                "rid": run_id,
                "ticker": c.ticker,
                "sector": c.sector,
                "name": c.company_name,
                "filed": c.filed,
                "sue": c.sue,
                "rev": c.rev_sue,
                "ni": c.ni_sue,
                "lag": c.lag_days,
                "pre": c.pre_vol,
                "pvol": c.predicted_vol,
                "exret": c.exret_63,
                "quint": c.sue_quintile,
            }
            for c in payload.companies
        ]
        await db.execute(
            text(
                """
                INSERT INTO stocks.companies
                    (run_id, ticker, sector, company_name, filed,
                     sue, rev_sue, ni_sue, lag_days, pre_vol,
                     predicted_vol, exret_63, sue_quintile)
                VALUES (:rid, :ticker, :sector, :name, :filed,
                        :sue, :rev, :ni, :lag, :pre, :pvol, :exret, :quint)
                """
            ),
            company_rows,
        )

        # --- 5. Track record (optional) ---
        if payload.track_record:
            track_rows = [
                {
                    "rid": run_id,
                    "period": t.period_label,
                    "ic": t.ic,
                    "ls": t.long_short_ret,
                    "n": t.n,
                }
                for t in payload.track_record
            ]
            await db.execute(
                text(
                    """
                    INSERT INTO stocks.track_record
                        (run_id, period_label, ic, long_short_ret, n)
                    VALUES (:rid, :period, :ic, :ls, :n)
                    """
                ),
                track_rows,
            )

    return IngestResponse(
        run_id=run_id,
        rows_written={
            "sectors": len(payload.sectors),
            "companies": len(payload.companies),
            "track_record": len(payload.track_record),
        },
    )


def _json(value) -> str:
    """Serialize a JSON-compatible Python value for a parameterized INSERT."""
    return json.dumps(value, default=str)

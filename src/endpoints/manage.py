"""Admin dashboard endpoints.

Signed-in admins only (an AuthAPI access token with role ADMIN). Everything
here is read-only and never cached.

GET /manage/health              Request counts and recent server errors
GET /manage/worldcup/runs       Every World Cup snapshot
GET /manage/worldcup/diff       How each team's odds moved between two snapshots
GET /manage/stocks/runs         Every stocks snapshot
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src import request_stats
from src.database import get_db, get_stocks_db
from src.models import StocksCompany, StocksRun, WorldCupRun, WorldCupTeamProbability

logger = logging.getLogger(__name__)

router = APIRouter()


class StatusCounts(BaseModel):
    ok: int
    redirects: int
    client_errors: int
    server_errors: int


class HourCounts(BaseModel):
    hour_start: int
    ok: int
    client_errors: int
    server_errors: int


class RouteCounts(BaseModel):
    route: str
    requests: int
    server_errors: int


class ServerError(BaseModel):
    at: float
    method: str
    route: str
    status: int
    ms: float
    request_id: str


class HealthResponse(BaseModel):
    counting_since: int | None
    last_hour: StatusCounts
    last_day: StatusCounts
    hourly: list[HourCounts]
    busiest_routes: list[RouteCounts]
    recent_errors: list[ServerError]


class WorldCupRunRow(BaseModel):
    id: int
    as_of_date: date
    label: str | None
    n_simulations: int
    n_played_matches_locked: int
    run_timestamp_utc: datetime
    teams: int


class WorldCupRunsResponse(BaseModel):
    runs: list[WorldCupRunRow]


class TeamChange(BaseModel):
    team: str
    winner_before: float | None
    winner_after: float | None
    winner_change: float
    final_before: float | None
    final_after: float | None


class WorldCupDiffResponse(BaseModel):
    before: WorldCupRunRow
    after: WorldCupRunRow
    teams: list[TeamChange]


class StocksRunRow(BaseModel):
    id: int
    as_of_date: date
    label: str | None
    universe_size: int
    n_events: int
    start_date: date
    end_date: date
    run_timestamp_utc: datetime
    companies: int


class StocksRunsResponse(BaseModel):
    runs: list[StocksRunRow]


def _counts(totals: dict[str, int]) -> StatusCounts:
    return StatusCounts(
        ok=totals["2xx"],
        redirects=totals["3xx"],
        client_errors=totals["4xx"],
        server_errors=totals["5xx"],
    )


def diff_teams(before: dict[str, tuple[float, float]], after: dict[str, tuple[float, float]]) -> list[TeamChange]:
    """Each team's winner and final odds in both snapshots, biggest move first."""
    rows = []
    for team in sorted(set(before) | set(after)):
        b, a = before.get(team), after.get(team)
        rows.append(TeamChange(
            team=team,
            winner_before=b[0] if b else None,
            winner_after=a[0] if a else None,
            winner_change=round((a[0] if a else 0.0) - (b[0] if b else 0.0), 4),
            final_before=b[1] if b else None,
            final_after=a[1] if a else None,
        ))
    rows.sort(key=lambda r: (-abs(r.winner_change), r.team))
    return rows


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    data = await run_in_threadpool(request_stats.summary)
    return HealthResponse(
        counting_since=int(data["counting_since"]) if data["counting_since"] is not None else None,
        last_hour=_counts(data["last_hour"]),
        last_day=_counts(data["last_day"]),
        hourly=[HourCounts(**h) for h in data["hourly"]],
        busiest_routes=[RouteCounts(**r) for r in data["busiest_routes"]],
        recent_errors=[ServerError(**e) for e in data["recent_errors"]],
    )


async def _worldcup_runs(db: AsyncSession, ids: list[int] | None = None) -> list[WorldCupRunRow]:
    teams = (
        select(WorldCupTeamProbability.run_id, func.count().label("teams"))
        .group_by(WorldCupTeamProbability.run_id)
        .subquery()
    )
    query = (
        select(WorldCupRun, func.coalesce(teams.c.teams, 0))
        .outerjoin(teams, teams.c.run_id == WorldCupRun.id)
        .order_by(WorldCupRun.as_of_date.desc(), WorldCupRun.id.desc())
    )
    if ids is not None:
        query = query.where(WorldCupRun.id.in_(ids))
    rows = (await db.execute(query)).all()
    return [
        WorldCupRunRow(
            id=run.id,
            as_of_date=run.as_of_date,
            label=run.label,
            n_simulations=run.n_simulations,
            n_played_matches_locked=run.n_played_matches_locked,
            run_timestamp_utc=run.run_timestamp_utc,
            teams=n,
        )
        for run, n in rows
    ]


@router.get("/worldcup/runs", response_model=WorldCupRunsResponse)
async def worldcup_runs(db: AsyncSession = Depends(get_db)) -> WorldCupRunsResponse:
    return WorldCupRunsResponse(runs=await _worldcup_runs(db))


@router.get("/worldcup/diff", response_model=WorldCupDiffResponse)
async def worldcup_diff(
    before: int = Query(..., description="Run id of the earlier snapshot"),
    after: int = Query(..., description="Run id of the later snapshot"),
    db: AsyncSession = Depends(get_db),
) -> WorldCupDiffResponse:
    runs = {r.id: r for r in await _worldcup_runs(db, [before, after])}
    if before not in runs or after not in runs:
        raise HTTPException(status_code=404, detail="No such snapshot")
    probs = (
        await db.execute(
            select(
                WorldCupTeamProbability.run_id,
                WorldCupTeamProbability.team,
                WorldCupTeamProbability.winner_pct,
                WorldCupTeamProbability.final_pct,
            ).where(WorldCupTeamProbability.run_id.in_([before, after]))
        )
    ).all()
    by_run: dict[int, dict[str, tuple[float, float]]] = {before: {}, after: {}}
    for run_id, team, winner, final in probs:
        by_run[run_id][team] = (float(winner), float(final))
    return WorldCupDiffResponse(
        before=runs[before],
        after=runs[after],
        teams=diff_teams(by_run[before], by_run[after]),
    )


@router.get("/stocks/runs", response_model=StocksRunsResponse)
async def stocks_runs(db: AsyncSession = Depends(get_stocks_db)) -> StocksRunsResponse:
    companies = (
        select(StocksCompany.run_id, func.count().label("companies"))
        .group_by(StocksCompany.run_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(StocksRun, func.coalesce(companies.c.companies, 0))
            .outerjoin(companies, companies.c.run_id == StocksRun.id)
            .order_by(StocksRun.as_of_date.desc(), StocksRun.id.desc())
        )
    ).all()
    return StocksRunsResponse(runs=[
        StocksRunRow(
            id=run.id,
            as_of_date=run.as_of_date,
            label=run.label,
            universe_size=run.universe_size,
            n_events=run.n_events,
            start_date=run.start_date,
            end_date=run.end_date,
            run_timestamp_utc=run.run_timestamp_utc,
            companies=n,
        )
        for run, n in rows
    ])

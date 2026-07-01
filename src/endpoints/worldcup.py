"""World Cup 2026 prediction endpoints.

All endpoints read from the `worldcup` schema in Postgres. They are
read-only and authenticate as the `worldcup_reader` role. Writes are the
responsibility of the ingestion script in the World Cup Prediction repo.

Endpoints
---------
GET /worldcup/latest          Summary of the most recent snapshot + leaderboard
GET /worldcup/bracket         Deterministic most-probable bracket
GET /worldcup/history         Per-team probability series across all runs
GET /worldcup/played-matches  Locked group-stage results for a run
"""

import logging
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import (
    WorldCupBracket,
    WorldCupPlayedMatch,
    WorldCupRun,
    WorldCupTeamProbability,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------
class RunMeta(BaseModel):
    id: int
    tournament_key: str
    as_of_date: date
    label: str | None
    n_simulations: int
    n_played_matches_locked: int
    run_timestamp_utc: datetime


class TeamRow(BaseModel):
    team: str
    winner_pct: float
    final_pct: float
    sf_pct: float
    qf_pct: float
    r16_pct: float
    r32_pct: float
    elo: float


class LatestResponse(BaseModel):
    run: RunMeta
    leaderboard: list[TeamRow]


class MatchDetail(BaseModel):
    teams: list[str]
    predicted_score: list[int]
    played: bool = False
    actual_score: list[int] | None = None
    went_to_penalties: bool = False
    winner: str | None = None


class BracketResponse(BaseModel):
    run_id: int
    as_of_date: date
    tournament_key: str
    group_winners: dict[str, list[str]]
    best_thirds: list[str]
    r32: list[list[str]]
    r16: list[list[str]]
    qf: list[list[str]]
    sf: list[list[str]]
    final_pair: list[str]
    champion: str
    # Per-round per-match scoreline records. None for old snapshots that
    # were pushed before the ingest endpoint accepted match_details.
    match_details: dict[str, list[MatchDetail]] | None = None


class HistoryPoint(BaseModel):
    as_of_date: date
    label: str | None
    n_played_matches_locked: int
    value: float


class TeamSeries(BaseModel):
    team: str
    points: list[HistoryPoint]


class HistoryResponse(BaseModel):
    tournament_key: str
    stage: str
    series: list[TeamSeries]


class PlayedMatch(BaseModel):
    match_date: date
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    group_name: str | None


class PlayedMatchesResponse(BaseModel):
    run: RunMeta
    matches: list[PlayedMatch]


STAGE_COLUMNS: dict[str, str] = {
    "winner": "winner_pct",
    "final": "final_pct",
    "sf": "sf_pct",
    "qf": "qf_pct",
    "r16": "r16_pct",
    "r32": "r32_pct",
}
StageLiteral = Literal["winner", "final", "sf", "qf", "r16", "r32"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _latest_run(
    db: AsyncSession,
    tournament_key: str,
) -> WorldCupRun:
    """Return the most recent run for a tournament, ordered by as_of_date
    then run_timestamp_utc so multiple same-day labels resolve to the
    chronologically last write.
    """
    result = await db.execute(
        select(WorldCupRun)
        .where(WorldCupRun.tournament_key == tournament_key)
        .order_by(
            WorldCupRun.as_of_date.desc(),
            WorldCupRun.run_timestamp_utc.desc(),
        )
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"No runs found for tournament {tournament_key!r}",
        )
    return run


def _run_to_meta(run: WorldCupRun) -> RunMeta:
    return RunMeta(
        id=run.id,
        tournament_key=run.tournament_key,
        as_of_date=run.as_of_date,
        label=run.label,
        n_simulations=run.n_simulations,
        n_played_matches_locked=run.n_played_matches_locked,
        run_timestamp_utc=run.run_timestamp_utc,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/latest", response_model=LatestResponse)
async def get_latest(
    tournament: str = Query(default="2026", description="Tournament key"),
    limit: int = Query(default=48, ge=1, le=200, description="Top-N teams to return"),
    db: AsyncSession = Depends(get_db),
):
    """Most recent snapshot summary plus the full leaderboard."""
    run = await _latest_run(db, tournament)

    result = await db.execute(
        select(WorldCupTeamProbability)
        .where(WorldCupTeamProbability.run_id == run.id)
        .order_by(WorldCupTeamProbability.winner_pct.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    leaderboard = [
        TeamRow(
            team=r.team,
            winner_pct=float(r.winner_pct),
            final_pct=float(r.final_pct),
            sf_pct=float(r.sf_pct),
            qf_pct=float(r.qf_pct),
            r16_pct=float(r.r16_pct),
            r32_pct=float(r.r32_pct),
            elo=float(r.elo),
        )
        for r in rows
    ]
    return LatestResponse(run=_run_to_meta(run), leaderboard=leaderboard)


@router.get("/bracket", response_model=BracketResponse)
async def get_bracket(
    tournament: str = Query(default="2026"),
    db: AsyncSession = Depends(get_db),
):
    """Deterministic most-probable bracket for the most recent run."""
    run = await _latest_run(db, tournament)

    result = await db.execute(
        select(WorldCupBracket).where(WorldCupBracket.run_id == run.id)
    )
    bracket = result.scalar_one_or_none()
    if bracket is None:
        raise HTTPException(
            status_code=404,
            detail=f"No bracket found for run {run.id}",
        )

    return BracketResponse(
        run_id=run.id,
        as_of_date=run.as_of_date,
        tournament_key=run.tournament_key,
        group_winners=bracket.group_winners,
        best_thirds=bracket.best_thirds,
        r32=bracket.r32,
        r16=bracket.r16,
        qf=bracket.qf,
        sf=bracket.sf,
        final_pair=bracket.final_pair,
        champion=bracket.champion,
        match_details=bracket.match_details,
    )


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    tournament: str = Query(default="2026"),
    stage: StageLiteral = Query(default="winner", description="Which probability column to return"),
    teams: str | None = Query(
        default=None,
        description="Comma-separated team names. If omitted, returns the top 10 teams by latest winner_pct.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Per-team probability series across every archived snapshot.

    Used by the UI's time-series chart. Snapshots are ordered chronologically;
    each point is `(as_of_date, value)` for the chosen stage.
    """
    column = STAGE_COLUMNS[stage]

    # Resolve the team filter. If none provided, fall back to the top 10
    # teams from the most recent snapshot.
    if teams:
        team_list = [t.strip() for t in teams.split(",") if t.strip()]
    else:
        latest = await _latest_run(db, tournament)
        latest_rows = await db.execute(
            select(WorldCupTeamProbability.team)
            .where(WorldCupTeamProbability.run_id == latest.id)
            .order_by(WorldCupTeamProbability.winner_pct.desc())
            .limit(10)
        )
        team_list = [t for (t,) in latest_rows.all()]

    if not team_list:
        return HistoryResponse(tournament_key=tournament, stage=stage, series=[])

    # Single query: join team_probabilities to runs and pull the requested
    # column. ORDER BY (team, as_of_date) keeps the Python regrouping cheap.
    sql = text(
        f"""
        SELECT
            tp.team,
            r.as_of_date,
            r.label,
            r.n_played_matches_locked,
            tp.{column}::float AS value
        FROM worldcup.team_probabilities tp
        JOIN worldcup.runs r ON r.id = tp.run_id
        WHERE r.tournament_key = :tk
          AND tp.team = ANY(:teams)
        ORDER BY tp.team, r.as_of_date, r.run_timestamp_utc
        """
    )
    result = await db.execute(sql, {"tk": tournament, "teams": team_list})

    series: dict[str, list[HistoryPoint]] = {t: [] for t in team_list}
    for row in result.mappings():
        series.setdefault(row["team"], []).append(
            HistoryPoint(
                as_of_date=row["as_of_date"],
                label=row["label"],
                n_played_matches_locked=row["n_played_matches_locked"],
                value=row["value"],
            )
        )

    return HistoryResponse(
        tournament_key=tournament,
        stage=stage,
        series=[TeamSeries(team=t, points=pts) for t, pts in series.items()],
    )


@router.get("/played-matches", response_model=PlayedMatchesResponse)
async def get_played_matches(
    tournament: str = Query(default="2026"),
    db: AsyncSession = Depends(get_db),
):
    """Locked group-stage results from the most recent snapshot."""
    run = await _latest_run(db, tournament)

    result = await db.execute(
        select(WorldCupPlayedMatch)
        .where(WorldCupPlayedMatch.run_id == run.id)
        .order_by(WorldCupPlayedMatch.match_date, WorldCupPlayedMatch.home_team)
    )
    rows = result.scalars().all()

    matches = [
        PlayedMatch(
            match_date=m.match_date,
            home_team=m.home_team,
            away_team=m.away_team,
            home_score=m.home_score,
            away_score=m.away_score,
            group_name=m.group_name,
        )
        for m in rows
    ]
    return PlayedMatchesResponse(run=_run_to_meta(run), matches=matches)

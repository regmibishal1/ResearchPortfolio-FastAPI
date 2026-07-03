"""Admin-only write endpoints for the worldcup schema.

Split from the read-side `worldcup` router so that the public read endpoints
can stay on the `has_api_key` gate while ingest is restricted to the
admin bearer token, never exposed to the UI.

Endpoints
---------
POST /worldcup/ingest    push a snapshot from a remote pipeline runner
"""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_writer_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------
class IngestRunMeta(BaseModel):
    tournament_key: str = "2026"
    as_of_date: date
    label: str | None = None
    n_simulations: int = Field(gt=0)
    n_played_matches_locked: int = Field(ge=0)
    run_timestamp_utc: datetime


class IngestTeamProb(BaseModel):
    team: str = Field(min_length=1, max_length=64)
    winner_pct: float = Field(ge=0, le=100)
    final_pct: float = Field(ge=0, le=100)
    sf_pct: float = Field(ge=0, le=100)
    qf_pct: float = Field(ge=0, le=100)
    r16_pct: float = Field(ge=0, le=100)
    r32_pct: float = Field(ge=0, le=100)
    elo: float


class TopFactor(BaseModel):
    """One SHAP-derived contributor to the model's matchup prediction.

    `impact` is the raw SHAP value on the predicted class from the base
    XGBoost model (calibrated probabilities preserve the ordering). `favors`
    names the team the feature pushed the prediction toward, or None on the
    rare draw prediction.
    """
    feature: str
    label: str
    value: float
    impact: float
    favors: str | None = None


class MatchDetail(BaseModel):
    """Per-match scoreline record. Predicted score always present (from the
    Poisson xG solver); actual_score + winner + went_to_penalties only
    populated for knockout matches that have been played.
    """
    teams: list[str] = Field(min_length=2, max_length=2)
    predicted_score: list[int] = Field(min_length=2, max_length=2)
    played: bool = False
    actual_score: list[int] | None = None
    went_to_penalties: bool = False
    winner: str | None = None
    top_factors: list[TopFactor] | None = None


class IngestBracket(BaseModel):
    group_winners: dict[str, list[str]]
    best_thirds: list[str]
    r32: list[list[str]]
    r16: list[list[str]]
    qf: list[list[str]]
    sf: list[list[str]]
    final_pair: list[str]
    champion: str = Field(min_length=1, max_length=64)
    # Per-round per-match scoreline details. Keyed by round name
    # ('R32'/'R16'/'QF'/'SF'/'Final'). Optional to keep the endpoint
    # backwards-compatible with older snapshot pushes.
    match_details: dict[str, list[MatchDetail]] | None = None


class IngestPlayedMatch(BaseModel):
    match_date: date
    home_team: str = Field(min_length=1, max_length=64)
    away_team: str = Field(min_length=1, max_length=64)
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    group_name: str | None = None


class IngestPayload(BaseModel):
    meta: IngestRunMeta
    team_probabilities: list[IngestTeamProb] = Field(min_length=1)
    bracket: IngestBracket
    played_matches: list[IngestPlayedMatch] = []


class IngestResponse(BaseModel):
    run_id: int
    rows_written: dict[str, int]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@router.post("/ingest", response_model=IngestResponse)
async def ingest_snapshot(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_writer_db),
):
    """Push a prediction snapshot into the worldcup schema.

    Idempotent: re-posting the same (tournament_key, as_of_date, label)
    upserts the run row and replaces every satellite row inside one
    transaction. Used both by the workstation primary path and the NAS
    fallback container.
    """
    logger.info(
        "ingest_snapshot tournament=%s as_of=%s label=%s teams=%d played=%d",
        payload.meta.tournament_key,
        payload.meta.as_of_date.isoformat(),
        payload.meta.label,
        len(payload.team_probabilities),
        len(payload.played_matches),
    )

    try:
        async with db.begin():
            # --- 1. Upsert the run row ---
            result = await db.execute(
                text(
                    """
                    INSERT INTO worldcup.runs
                        (tournament_key, as_of_date, label, n_simulations,
                         n_played_matches_locked, run_timestamp_utc, metadata)
                    VALUES (:tk, :date, :label, :nsim, :nplay, :ts, '{}'::jsonb)
                    ON CONFLICT (tournament_key, as_of_date, label) DO UPDATE
                        SET n_simulations           = EXCLUDED.n_simulations,
                            n_played_matches_locked = EXCLUDED.n_played_matches_locked,
                            run_timestamp_utc       = EXCLUDED.run_timestamp_utc
                    RETURNING id
                    """
                ),
                {
                    "tk": payload.meta.tournament_key,
                    "date": payload.meta.as_of_date,
                    "label": payload.meta.label,
                    "nsim": payload.meta.n_simulations,
                    "nplay": payload.meta.n_played_matches_locked,
                    "ts": payload.meta.run_timestamp_utc,
                },
            )
            run_id: int = result.scalar_one()

            # --- 2. Replace satellite tables for this run ---
            for table in ("team_probabilities", "brackets", "played_matches"):
                await db.execute(
                    text(f"DELETE FROM worldcup.{table} WHERE run_id = :rid"),
                    {"rid": run_id},
                )

            # --- 3. Team probabilities ---
            team_rows = [
                {
                    "rid": run_id,
                    "team": p.team,
                    "win": p.winner_pct, "fin": p.final_pct, "sf": p.sf_pct,
                    "qf": p.qf_pct, "r16": p.r16_pct, "r32": p.r32_pct,
                    "elo": p.elo,
                }
                for p in payload.team_probabilities
            ]
            await db.execute(
                text(
                    """
                    INSERT INTO worldcup.team_probabilities
                        (run_id, team, winner_pct, final_pct, sf_pct,
                         qf_pct, r16_pct, r32_pct, elo)
                    VALUES (:rid, :team, :win, :fin, :sf, :qf, :r16, :r32, :elo)
                    """
                ),
                team_rows,
            )

            # --- 4. Bracket ---
            b = payload.bracket
            # Serialize match_details Pydantic models to plain dicts for JSONB
            # storage. None if the payload didn't include them (old snapshots).
            if b.match_details is None:
                md_json = None
            else:
                md_json = _json(
                    {
                        round_name: [m.model_dump() for m in matches]
                        for round_name, matches in b.match_details.items()
                    }
                )
            await db.execute(
                text(
                    """
                    INSERT INTO worldcup.brackets
                        (run_id, group_winners, best_thirds, r32, r16, qf, sf,
                         final_pair, champion, match_details)
                    VALUES (:rid, CAST(:gw AS jsonb), CAST(:bt AS jsonb),
                            CAST(:r32 AS jsonb), CAST(:r16 AS jsonb),
                            CAST(:qf AS jsonb), CAST(:sf AS jsonb),
                            CAST(:fp AS jsonb), :champ,
                            CAST(:md AS jsonb))
                    """
                ),
                {
                    "rid": run_id,
                    "gw": _json(b.group_winners),
                    "bt": _json(b.best_thirds),
                    "r32": _json(b.r32),
                    "r16": _json(b.r16),
                    "qf": _json(b.qf),
                    "sf": _json(b.sf),
                    "fp": _json(b.final_pair),
                    "champ": b.champion,
                    "md": md_json,
                },
            )

            # --- 5. Played matches (optional) ---
            if payload.played_matches:
                match_rows = [
                    {
                        "rid": run_id,
                        "md": m.match_date,
                        "h": m.home_team, "a": m.away_team,
                        "hs": m.home_score, "as": m.away_score,
                        "g": m.group_name,
                    }
                    for m in payload.played_matches
                ]
                await db.execute(
                    text(
                        """
                        INSERT INTO worldcup.played_matches
                            (run_id, match_date, home_team, away_team,
                             home_score, away_score, group_name)
                        VALUES (:rid, :md, :h, :a, :hs, :as, :g)
                        """
                    ),
                    match_rows,
                )

    except RuntimeError as exc:
        # Raised by get_writer_db() when WORLDCUP_DB_WRITER_URL is unset.
        logger.error("ingest_snapshot disabled: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Ingest is not configured on this server.",
        )

    return IngestResponse(
        run_id=run_id,
        rows_written={
            "team_probabilities": len(payload.team_probabilities),
            "brackets": 1,
            "played_matches": len(payload.played_matches),
        },
    )


def _json(value) -> str:
    """Serialize a JSON-compatible Python value for a parameterized INSERT."""
    import json as _stdlib_json
    return _stdlib_json.dumps(value, default=str)

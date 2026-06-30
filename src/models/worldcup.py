"""ORM models for the `worldcup` schema.

Each prediction run produces one row in `worldcup.runs` plus N rows in the
satellite tables. The schema is intentionally narrow — every percentage is
stored as NUMERIC(7,4) so probabilities round-trip exactly, and structural
data (bracket pairings) lives in JSONB to avoid a brittle pairing-by-pairing
schema.
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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

WORLDCUP_SCHEMA = "worldcup"


class WorldCupRun(Base):
    """One row per prediction snapshot."""

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint(
            "tournament_key", "as_of_date", "label",
            name="uq_worldcup_runs_tournament_date_label",
        ),
        Index(
            "ix_worldcup_runs_tournament_as_of_date",
            "tournament_key", "as_of_date",
            postgresql_using="btree",
        ),
        CheckConstraint("n_simulations > 0", name="ck_worldcup_runs_n_simulations_pos"),
        CheckConstraint(
            "n_played_matches_locked >= 0",
            name="ck_worldcup_runs_n_played_nonneg",
        ),
        {"schema": WORLDCUP_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tournament_key: Mapped[str] = mapped_column(String(16), nullable=False, default="2026")
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    n_simulations: Mapped[int] = mapped_column(Integer, nullable=False)
    n_played_matches_locked: Mapped[int] = mapped_column(Integer, nullable=False)
    run_timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    team_probabilities: Mapped[list["WorldCupTeamProbability"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    bracket: Mapped["WorldCupBracket | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    played_matches: Mapped[list["WorldCupPlayedMatch"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class WorldCupTeamProbability(Base):
    """Per-team stage-reach probabilities for a single run."""

    __tablename__ = "team_probabilities"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "team", name="pk_worldcup_team_probabilities"),
        Index(
            "ix_worldcup_team_probabilities_team_run",
            "team", "run_id",
        ),
        {"schema": WORLDCUP_SCHEMA},
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{WORLDCUP_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    team: Mapped[str] = mapped_column(String(64), nullable=False)
    winner_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    final_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    sf_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    qf_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    r16_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    r32_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    elo: Mapped[float] = mapped_column(Numeric(7, 1), nullable=False)

    run: Mapped["WorldCupRun"] = relationship(back_populates="team_probabilities")


class WorldCupBracket(Base):
    """Deterministic most-probable bracket for a single run."""

    __tablename__ = "brackets"
    __table_args__ = ({"schema": WORLDCUP_SCHEMA},)

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{WORLDCUP_SCHEMA}.runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # group_winners: {"A": ["Mexico", "South Korea"], "B": [...], ...}
    group_winners: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # best_thirds: ["DR Congo", "Sweden", ...] in ranked order
    best_thirds: Mapped[list] = mapped_column(JSONB, nullable=False)
    # r32 / r16 / qf / sf: list of [team1, team2] pairs
    r32: Mapped[list] = mapped_column(JSONB, nullable=False)
    r16: Mapped[list] = mapped_column(JSONB, nullable=False)
    qf: Mapped[list] = mapped_column(JSONB, nullable=False)
    sf: Mapped[list] = mapped_column(JSONB, nullable=False)
    # `final` is a Postgres reserved word; the column is named final_pair.
    # Stored as a 2-element array: [team1, team2]
    final_pair: Mapped[list] = mapped_column("final_pair", JSONB, nullable=False)
    champion: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped["WorldCupRun"] = relationship(back_populates="bracket")


class WorldCupPlayedMatch(Base):
    """Group-stage matches that were locked into this run as ground truth."""

    __tablename__ = "played_matches"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id", "match_date", "home_team", "away_team",
            name="pk_worldcup_played_matches",
        ),
        CheckConstraint("home_score >= 0", name="ck_worldcup_played_home_score_nonneg"),
        CheckConstraint("away_score >= 0", name="ck_worldcup_played_away_score_nonneg"),
        {"schema": WORLDCUP_SCHEMA},
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{WORLDCUP_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_date: Mapped[date] = mapped_column(Date, nullable=False)
    home_team: Mapped[str] = mapped_column(String(64), nullable=False)
    away_team: Mapped[str] = mapped_column(String(64), nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(2), nullable=True)

    run: Mapped["WorldCupRun"] = relationship(back_populates="played_matches")

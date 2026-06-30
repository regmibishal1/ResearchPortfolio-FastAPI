"""Model package — re-exports `Base` and every ORM class so Alembic's
autogenerate sees the full metadata graph from one import.
"""

from src.models.base import Base
from src.models.worldcup import (
    WorldCupBracket,
    WorldCupPlayedMatch,
    WorldCupRun,
    WorldCupTeamProbability,
)

__all__ = [
    "Base",
    "WorldCupBracket",
    "WorldCupPlayedMatch",
    "WorldCupRun",
    "WorldCupTeamProbability",
]

"""Model package, re-exports `Base` and every ORM class so Alembic's
autogenerate sees the full metadata graph from one import.
"""

from src.models.base import Base
from src.models.stocks import (
    StocksCompany,
    StocksRun,
    StocksSector,
    StocksTrackRecord,
)
from src.models.worldcup import (
    WorldCupBracket,
    WorldCupPlayedMatch,
    WorldCupRun,
    WorldCupTeamProbability,
)

__all__ = [
    "Base",
    "StocksCompany",
    "StocksRun",
    "StocksSector",
    "StocksTrackRecord",
    "WorldCupBracket",
    "WorldCupPlayedMatch",
    "WorldCupRun",
    "WorldCupTeamProbability",
]

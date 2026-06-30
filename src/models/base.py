"""SQLAlchemy declarative base.

All ORM models inherit from `Base`. Alembic reads `Base.metadata` to drive
autogenerate diffs against the live database.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

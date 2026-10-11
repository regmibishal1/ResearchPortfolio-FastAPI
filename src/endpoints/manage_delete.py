"""Admin dashboard: deleting snapshots.

Split from the read-only `manage` router so that only these two routes get
the writer connections. Same gate as `manage` (API key plus an AuthAPI
access token with role ADMIN). A delete removes the run and, through the
foreign keys, everything that belongs to it. There are no backups, so the
dashboard asks for confirmation first, and every delete is logged with the
admin who made it.

DELETE /manage/worldcup/runs/{run_id}
DELETE /manage/stocks/runs/{run_id}
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_stocks_writer_db, get_writer_db
from src.dependency import has_admin_role
from src.models import StocksRun, WorldCupRun

logger = logging.getLogger(__name__)

router = APIRouter()


async def _delete(db: AsyncSession, model, run_id: int, admin: dict, kind: str) -> None:
    run = await db.get(model, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such snapshot")
    as_of, label = run.as_of_date, run.label
    # One statement; the database's ON DELETE CASCADE removes the rest.
    await db.execute(delete(model).where(model.id == run_id))
    await db.commit()
    logger.warning(
        "Admin %s deleted %s run id=%s as_of=%s label=%s",
        admin.get("sub"), kind, run_id, as_of, label,
    )


@router.delete("/worldcup/runs/{run_id}", status_code=204)
async def delete_worldcup_run(
    run_id: int,
    admin: dict = Depends(has_admin_role),
    db: AsyncSession = Depends(get_writer_db),
) -> None:
    # Returning nothing keeps the no-store header the router adds.
    await _delete(db, WorldCupRun, run_id, admin, "worldcup")


@router.delete("/stocks/runs/{run_id}", status_code=204)
async def delete_stocks_run(
    run_id: int,
    admin: dict = Depends(has_admin_role),
    db: AsyncSession = Depends(get_stocks_writer_db),
) -> None:
    await _delete(db, StocksRun, run_id, admin, "stocks")

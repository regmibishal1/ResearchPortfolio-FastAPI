import logging

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
from src.endpoints import health, manage, stats, stocks, stocks_admin, worldcup, worldcup_admin
from src.dependency import (
    has_admin_access,
    has_admin_role,
    has_api_key,
    set_no_store,
    set_read_cache,
    set_worldcup_cache,
)
from src.logging_config import setup_logging
from src.middleware import RequestLoggingMiddleware

# Initialise structured logging before the app is created so that startup
# messages (e.g. Uvicorn's "Application startup complete") are formatted too.
setup_logging(level=logging.DEBUG if settings.debug else logging.INFO)

# The interactive docs and the schema behind them are only served in debug,
# so production does not publish a map of every route.
docs_enabled = bool(settings.debug)
app = FastAPI(
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

# The browser reads public data with an API key, and the admin dashboard also
# sends its AuthAPI bearer token. No cookies or credentials, and only the
# headers the UI sends.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    max_age=86400,
)

# RequestLoggingMiddleware is added last so Starlette's LIFO ordering makes it
# run outermost, it sees every request before CORS and every response after.
app.add_middleware(RequestLoggingMiddleware)

app.include_router(
    health.router
)

# Semi-public endpoints, API key required (shared with Angular UI).
# Not user-auth (no login needed), but prevents anonymous bot abuse of
# CPU-intensive sampling endpoints.
app.include_router(
    stats.router,
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(has_api_key)],
)

# World Cup 2026, read-only endpoints backed by the worldcup Postgres
# schema. Same API-key gate as /stats; database connection authenticates
# as worldcup_reader (SELECT-only role).
app.include_router(
    worldcup.router,
    prefix="/worldcup",
    tags=["worldcup"],
    dependencies=[Depends(has_api_key), Depends(set_worldcup_cache)],
)

# World Cup 2026 admin, write endpoint used by the prediction pipeline
# runners (workstation or NAS container). Gated by the admin bearer
# token and authenticates as worldcup_writer for DB writes. Mounted as a
# separate router so the read endpoints can never accidentally get the
# writer credentials wired into their request scope.
app.include_router(
    worldcup_admin.router,
    prefix="/worldcup",
    tags=["worldcup-admin"],
    dependencies=[Depends(has_admin_access)],
)

# EDGAR fundamentals signals, read-only endpoints backed by the stocks
# Postgres schema. Same API-key gate as /stats; database connection
# authenticates as stocks_reader (SELECT-only role).
app.include_router(
    stocks.router,
    prefix="/stocks",
    tags=["stocks"],
    dependencies=[Depends(has_api_key), Depends(set_read_cache)],
)

# Stocks admin, write endpoint used by the edgar-signals pipeline. Gated by
# the admin bearer token and authenticates as stocks_writer for DB writes.
# Separate router so the read endpoints never get writer credentials wired
# into their request scope.
app.include_router(
    stocks_admin.router,
    prefix="/stocks",
    tags=["stocks-admin"],
    dependencies=[Depends(has_admin_access)],
)

# Admin dashboard, read-only. Signed-in admins only: an AuthAPI access token
# with role ADMIN, on top of the usual API key. Answers are never cached.
app.include_router(
    manage.router,
    prefix="/manage",
    tags=["manage"],
    dependencies=[Depends(has_api_key), Depends(has_admin_role), Depends(set_no_store)],
)

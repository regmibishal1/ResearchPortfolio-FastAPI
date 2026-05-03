import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from src.endpoints import hello, health, stats
from src.dependency import has_access, has_api_key
from src.logging_config import setup_logging
from src.middleware import RequestLoggingMiddleware

# Initialise structured logging before the app is created so that startup
# messages (e.g. Uvicorn's "Application startup complete") are formatted too.
setup_logging(level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO)

app = FastAPI()

_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:4200")
allowed_origins = [o.strip() for o in _origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RequestLoggingMiddleware is added last so Starlette's LIFO ordering makes it
# run outermost — it sees every request before CORS and every response after.
app.add_middleware(RequestLoggingMiddleware)

# routes
PROTECTED = [Depends(has_access)]

app.include_router(
    hello.router,
    prefix="/hello",
    dependencies=PROTECTED
)

app.include_router(
    health.router
)

# Semi-public endpoints — API key required (shared with Angular UI).
# Not user-auth (no login needed), but prevents anonymous bot abuse of
# CPU-intensive sampling endpoints.
app.include_router(
    stats.router,
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(has_api_key)],
)

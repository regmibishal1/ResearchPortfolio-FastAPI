import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from src.endpoints import hello, health, stats
from src.dependency import has_access

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

# Public endpoints — no auth required
app.include_router(
    stats.router,
    prefix="/stats",
    tags=["stats"],
)

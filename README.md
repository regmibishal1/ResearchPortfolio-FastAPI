# ResearchPortfolio-FastAPI

FastAPI service powering the interactive demos on my research portfolio. Model and calculation endpoints run live server-side rather than as static screenshots.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness probe |
| POST | `/stats/sample` | API key | Statistical distribution sampler |
| GET | `/worldcup/latest` | API key | Most recent prediction snapshot and leaderboard |
| GET | `/worldcup/bracket` | API key | Most-probable bracket for the latest run |
| GET | `/worldcup/history` | API key | Per-team probability series across runs |
| GET | `/worldcup/played-matches` | API key | Locked group-stage results for the latest run |
| POST | `/worldcup/ingest` | admin bearer | Snapshot ingestion from the prediction pipeline |
| GET | `/stocks/latest` | API key | Latest fundamentals snapshot, metrics, and sector heatmap |
| GET | `/stocks/companies` | API key | Per-company signals for the latest snapshot |
| GET | `/stocks/company/{ticker}` | API key | One company's signal plus its history across snapshots |
| GET | `/stocks/track-record` | API key | Realized walk-forward track record for the latest snapshot |
| GET | `/stocks/history` | API key | A single run-level metric across snapshots |
| POST | `/stocks/ingest` | admin bearer | Snapshot ingestion from the edgar-signals pipeline |

### Authentication tiers

- **API key** (`X-API-Key` header): lightweight gate on public demo endpoints to deter bot abuse; rate limiting and CORS provide the real protection.
- **Admin bearer token**: internal pipeline operations only, never exposed to the browser.
- **JWT bearer** (HS256, issued by the AuthAPI): available for user-scoped endpoints via `src/dependency.py`.

## Stack

- Python 3.10, FastAPI, Pydantic v2
- SQLAlchemy 2 (async) + PostgreSQL, migrations via Alembic
- Gunicorn with Uvicorn workers in production; Uvicorn reload for development
- Structured request-scoped logging with request-ID tracing and real client IP resolution

## Configuration

All configuration comes from environment variables. No secrets are committed to this repository.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Read-side Postgres connection (SELECT-only role) |
| `WORLDCUP_DB_WRITER_URL` | Write-side connection used only by the worldcup ingest endpoint |
| `STOCKS_DB_READER_URL` | Read-side connection for the stocks schema (SELECT-only role); falls back to `DATABASE_URL` when unset |
| `STOCKS_DB_WRITER_URL` | Write-side connection used only by the stocks ingest endpoint |
| `RP_FASTAPI_JWT_SECRET` | Shared secret for verifying JWTs issued by the AuthAPI |
| `RP_ADMIN_TOKEN` | Bearer token for admin-only operations |
| `RP_FASTAPI_API_KEY` | API key required by demo endpoints |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowlist of frontend origins |
| `DEBUG` | Any non-empty value enables debug logging |

Endpoints degrade gracefully when optional configuration is absent: database-backed routes return `503` if their connection string is unset, so the service still runs in minimal environments.

## Development

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export RP_FASTAPI_API_KEY=dev-key
export CORS_ALLOWED_ORIGINS=http://localhost:4200

uvicorn src.main:app --reload --port 8000
```

Interactive API docs are available at `http://localhost:8000/docs` while the server is running.

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Smoke tests cover app startup, `/health`, request-ID propagation, and the API key gate on `/stats`. They run without a database and execute in CI on every pull request.

## Docker

```bash
docker build -t researchportfolio-fastapi .
docker run --rm -p 8000:8000 \
  -e RP_FASTAPI_API_KEY=dev-key \
  -e CORS_ALLOWED_ORIGINS=http://localhost:4200 \
  researchportfolio-fastapi
```

In production the service runs behind a Cloudflare Tunnel alongside the AuthAPI and PostgreSQL, with each component connecting to the database under its own least-privilege role.

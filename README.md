# ResearchPortfolio-FastAPI

FastAPI service powering the interactive demos on my research portfolio. Model and calculation endpoints run live server-side rather than as static screenshots.

To report a security problem privately, see [SECURITY.md](SECURITY.md).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness probe |
| POST | `/stats/sample` | API key | Statistical distribution sampler |
| GET | `/worldcup/latest` | API key | Most recent prediction snapshot and leaderboard |
| GET | `/worldcup/bracket` | API key | Most-probable bracket for the latest run |
| GET | `/worldcup/report-card` | API key | Walk-forward model evaluation for a run |
| GET | `/worldcup/scenarios` | API key | What-if championship odds for upcoming matches |
| GET | `/worldcup/retrospective` | API key | Post-tournament wrap-up for a run |
| GET | `/worldcup/history` | API key | Per-team probability series across runs |
| GET | `/worldcup/played-matches` | API key | Locked group-stage results for the latest run |
| POST | `/worldcup/ingest` | admin bearer | Snapshot ingestion from the prediction pipeline |
| GET | `/stocks/latest` | API key | Latest fundamentals snapshot, metrics, and sector heatmap |
| GET | `/stocks/companies` | API key | Per-company signals for the latest snapshot |
| GET | `/stocks/company/{ticker}` | API key | One company's signal plus its history across snapshots |
| GET | `/stocks/track-record` | API key | Realized walk-forward track record for the latest snapshot |
| GET | `/stocks/history` | API key | A single run-level metric across snapshots |
| POST | `/stocks/ingest` | admin bearer | Snapshot ingestion from the edgar-signals pipeline |
| GET | `/manage/health` | admin role | Request counts by status and route for the last hour and day, plus recent server errors |
| GET | `/manage/worldcup/runs` | admin role | Every World Cup snapshot with its team count |
| GET | `/manage/worldcup/diff?before=&after=` | admin role | How each team's winner and final odds moved between two snapshots |
| GET | `/manage/stocks/runs` | admin role | Every stocks snapshot with its company count |
| DELETE | `/manage/worldcup/runs/{run_id}`, `/manage/stocks/runs/{run_id}` | admin role | Delete a snapshot and everything in it (writer connection; logged with the admin's username; no undo) |

### World Cup routes are an archive

The 2026 tournament ended on July 19, and the last snapshot was ingested that day. The site no longer calls `/worldcup/*`: it reads a frozen export of these routes, written by `scripts/export-worldcup.mjs` in the UI repo. The routes stay up as the source of that export and as a record of every daily run; nothing ingests new snapshots now.

### Authentication tiers

- **API key** (`X-API-Key` header): lightweight gate on public demo endpoints to deter bot abuse; rate limiting and CORS provide the real protection.
- **Admin bearer token**: internal pipeline operations only, never exposed to the browser.
- **JWT bearer** (HMAC with the shared secret, HS256, HS384 or HS512, issued by the AuthAPI): available for user-scoped endpoints via `src/dependency.py`.
- **Admin role** (`has_admin_role`): an AuthAPI access token whose `role` claim is `ADMIN`, plus the API key. Used by the site's admin dashboard; answers are `Cache-Control: no-store`.

## Stack

- Python 3.13, FastAPI, Pydantic v2
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
| `DEBUG` | Any non-empty value enables debug logging and the interactive docs |
| `WEB_CONCURRENCY` | Gunicorn worker count in the container (default 4) |
| `RP_REQUEST_STATS_PATH` | Where the dashboard's request counts are kept (SQLite, shared by the workers); defaults to the system temp folder, so a restart starts them again |

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

Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are served only when `DEBUG` is set, so production does not publish them. Run with `DEBUG=1` locally to use them.

### Dependencies

`requirements.in` lists the direct dependencies; `requirements.txt` is compiled from it with exact versions and hashes, so installs are reproducible and checked. To add or upgrade a package, edit the `.in` file and recompile with [pip-tools](https://pip-tools.readthedocs.io/):

```bash
pip install pip-tools
pip-compile --generate-hashes --allow-unsafe --strip-extras requirements.in
pip-compile --generate-hashes --allow-unsafe --strip-extras requirements-dev.in
```

CI runs `pip-audit` against both files, and Dependabot proposes monthly updates.

### API schema

`openapi.json` is the committed OpenAPI schema. The UI generates its TypeScript types from it and checks its interfaces against them, so the two cannot drift silently. After changing a request or response model, regenerate it (a test fails until you do) and copy it to the UI's `src/app/api/fastapi-openapi.json`:

```bash
python scripts/export_openapi.py
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Smoke tests cover app startup, `/health`, request-ID propagation, the API key and admin gates, the production defaults (no public docs, a narrow CORS policy) and the JWT check. They run without a database and execute in CI on every pull request. A missing API key or bearer token gets `401`; a wrong one gets `403`.

## Docker

```bash
docker build -t researchportfolio-fastapi .
docker run --rm -p 8000:8000 \
  -e RP_FASTAPI_API_KEY=dev-key \
  -e CORS_ALLOWED_ORIGINS=http://localhost:4200 \
  researchportfolio-fastapi
```

The image runs as an unprivileged user and has a `HEALTHCHECK` on `/health`. In production the service runs behind a Cloudflare Tunnel alongside the AuthAPI and PostgreSQL, with each component connecting to the database under its own least-privilege role.

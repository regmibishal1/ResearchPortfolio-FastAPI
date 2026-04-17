# ResearchPortfolio-FastAPI

Python/FastAPI service for the Research Portfolio. Hosts interactive model and calculation endpoints so research demos can run live instead of as static notebook screenshots. Self-hosted on a NAS behind a Cloudflare Tunnel at `api.bishalregmi.com`.

JWT-protected endpoints share a secret with [`ResearchPortfolio-AuthAPI`](https://github.com/regmibishal1/ResearchPortfolio-AuthAPI) — tokens minted by the auth server are accepted here.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | — | Liveness probe |
| GET | `/hello` | Bearer | Demo endpoint (to be replaced with real model routes) |

Planned: research/ML inference endpoints backing the portfolio's interactive demos.

## Stack

- FastAPI 0.110 on Python 3.10
- Gunicorn + Uvicorn workers (prod), Uvicorn reload (dev)
- `python-jose` for JWT validation (HS256, secret shared with AuthAPI)

## Environment variables

| Var | Purpose |
|---|---|
| `RP_API_SEC_TOKEN` | Base64 HS256 secret (must match AuthAPI) |

## Local development

```bash
python -m venv venv
source venv/bin/activate           # or venv\Scripts\activate on Windows
pip install -r requirements.txt

export RP_API_SEC_TOKEN=...         # same value as AuthAPI
uvicorn src.main:app --reload --port 8000
```

## Docker

```bash
docker build -t researchportfolio-fastapi .
docker run --rm -p 8000:8000 -e RP_API_SEC_TOKEN=... researchportfolio-fastapi
```

In production this runs via the top-level `docker-compose.yml` alongside the AuthAPI, PostgreSQL, and `cloudflared`.

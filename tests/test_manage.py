"""The admin dashboard API: admins only, never cached, and request stats
that keep no request details beyond the route."""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("RP_FASTAPI_API_KEY", "test-key-for-ci-only")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import request_stats  # noqa: E402
from src.endpoints.manage import diff_teams  # noqa: E402
from src.main import app  # noqa: E402

client = TestClient(app)
API_KEY = os.environ["RP_FASTAPI_API_KEY"]
SECRET = base64.b64encode(os.urandom(48)).decode()


def _token(**claims) -> str:
    body = {"sub": "someone", "typ": "access", "exp": int(time.time()) + 60, **claims}
    return jwt.encode(body, base64.b64decode(SECRET), algorithm="HS256")


def _get(path: str, token: str | None = None):
    headers = {"X-API-Key": API_KEY}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.get(path, headers=headers)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("RP_FASTAPI_JWT_SECRET", SECRET)
    monkeypatch.setattr(request_stats, "DB_PATH", tmp_path / "stats.sqlite3")
    monkeypatch.setattr(request_stats, "_conn", None)


def test_manage_needs_a_signed_in_admin():
    assert _get("/manage/health").status_code in (401, 403)
    user = _get("/manage/health", _token(role="USER"))
    assert user.status_code == 403
    assert user.json()["detail"] == "Admins only"
    assert _get("/manage/health", _token(role="ADMIN", typ="refresh")).status_code == 401


def test_admin_answers_are_never_cached():
    response = _get("/manage/health", _token(role="ADMIN"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_health_counts_requests_by_route_but_not_health_probes():
    client.get("/health")
    _get("/stats/sample")  # 405: a GET on a POST route
    _get("/no/such/path")
    data = _get("/manage/health", _token(role="ADMIN")).json()
    assert data["last_hour"]["client_errors"] >= 2
    routes = {r["route"] for r in data["busiest_routes"]}
    assert "/health" not in routes
    assert "unmatched" in routes
    assert len(data["hourly"]) == 24


def test_server_errors_keep_only_the_route_status_and_request_id():
    now = time.time()
    request_stats.record("GET", "/stocks/company/{ticker}", 503, 12.34, "abc123", now=now)
    request_stats.record("GET", "/stocks/company/{ticker}", 200, 5.0, "def456", now=now)
    data = request_stats.summary(now=now)
    assert data["last_hour"]["5xx"] == 1
    assert data["recent_errors"] == [{
        "at": now, "method": "GET", "route": "/stocks/company/{ticker}",
        "status": 503, "ms": 12.3, "request_id": "abc123",
    }]


def test_runs_without_a_database_return_503():
    assert _get("/manage/worldcup/runs", _token(role="ADMIN")).status_code == 503


def test_cors_lets_the_dashboard_send_its_bearer_token():
    response = client.options(
        "/manage/health",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-api-key",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-credentials" not in response.headers


def test_diff_lists_the_biggest_moves_first():
    rows = diff_teams(
        {"Spain": (20.0, 35.0), "Brazil": (15.0, 30.0), "Japan": (1.0, 3.0)},
        {"Spain": (12.0, 25.0), "Brazil": (30.0, 50.0), "Morocco": (2.0, 5.0)},
    )
    assert [r.team for r in rows] == ["Brazil", "Spain", "Morocco", "Japan"]
    assert rows[0].winner_change == 15.0
    japan = rows[-1]
    assert japan.winner_after is None and japan.winner_change == -1.0

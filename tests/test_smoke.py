"""Smoke tests for the app wiring: startup, health, and the API key gate.

These run without a database; endpoints backed by Postgres are exercised
in deployment, not here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("RP_FASTAPI_API_KEY", "test-key-for-ci-only")

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402

client = TestClient(app)
API_KEY = os.environ["RP_FASTAPI_API_KEY"]


def test_health_is_public():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stats_requires_api_key():
    response = client.post(
        "/stats/sample",
        json={"distribution": "normal", "params": {}},
    )
    assert response.status_code == 403


def test_stats_rejects_wrong_api_key():
    response = client.post(
        "/stats/sample",
        json={"distribution": "normal", "params": {}},
        headers={"X-API-Key": "not-the-key"},
    )
    assert response.status_code == 403


def test_stats_sample_with_api_key():
    response = client.post(
        "/stats/sample",
        json={"distribution": "normal", "params": {"mean": 0, "std": 1}, "n_samples": 500},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["n_samples"] == 500
    assert len(body["histogram"]) > 0
    total = sum(b["count"] for b in body["histogram"])
    assert total == 500


def test_stats_validates_params():
    response = client.post(
        "/stats/sample",
        json={"distribution": "normal", "params": {"std": -1}},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 400


def test_request_id_header_present():
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 12

"""Input limits: body size caps that apply before any auth, sampler bounds,
key comparisons that cannot crash, and the startup configuration check."""
import base64
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("RP_FASTAPI_API_KEY", "test-key-for-ci-only")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import dependency  # noqa: E402
from src.body_limit import DEFAULT_LIMIT, INGEST_LIMIT  # noqa: E402
from src.config import Settings  # noqa: E402
from src.endpoints.stocks_admin import IngestRunMeta  # noqa: E402
from src.main import app  # noqa: E402

client = TestClient(app)
API_KEY = os.environ["RP_FASTAPI_API_KEY"]


def _sample(params: dict, distribution: str = "normal"):
    return client.post(
        "/stats/sample",
        json={"distribution": distribution, "params": params, "n_samples": 100},
        headers={"X-API-Key": API_KEY},
    )


@pytest.mark.parametrize(
    "path,limit",
    [("/stats/sample", DEFAULT_LIMIT), ("/worldcup/ingest", INGEST_LIMIT)],
)
def test_an_oversized_body_is_refused_before_auth(path, limit):
    # No key or token: the cap answers first, so nobody can make the worker
    # parse a huge body for free.
    response = client.post(
        path,
        content=b"x" * (limit + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_a_streamed_body_past_the_cap_is_refused():
    def chunks():
        for _ in range(DEFAULT_LIMIT // 1024 + 2):
            yield b"x" * 1024

    response = client.post(
        "/stats/sample",
        content=chunks(),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
    )
    assert response.status_code == 413


def test_a_bad_content_length_is_refused():
    response = client.post(
        "/stats/sample",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "-1"},
    )
    assert response.status_code == 413


def test_a_normal_body_still_goes_through():
    assert _sample({"mean": 0, "std": 1}).status_code == 200


@pytest.mark.parametrize(
    "params",
    [{"mean": 0, "std": 1e308}, {"mean": 1e12, "std": 1}, {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}],
    ids=["huge-std", "huge-mean", "too-many"],
)
def test_out_of_range_sampler_params_are_rejected(params):
    assert _sample(params).status_code == 422


def test_non_finite_sampler_params_are_rejected():
    response = client.post(
        "/stats/sample",
        content=b'{"distribution": "normal", "params": {"mean": 0, "std": Infinity}}',
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "inf"


def test_params_numpy_refuses_are_a_400_not_a_500():
    # In range for the model, but not a valid Poisson rate for numpy.
    assert _sample({"lam": 1e9 + 0.0}, "poisson").status_code in (200, 400)
    assert _sample({"n": -5, "p": 0.5}, "binomial").status_code == 400


def test_a_non_ascii_api_key_is_a_403_not_a_crash():
    response = client.post(
        "/stats/sample",
        json={"distribution": "normal", "params": {"mean": 0, "std": 1}},
        headers={"X-API-Key": "café".encode("utf-8")},
    )
    assert response.status_code == 403


def test_a_non_ascii_admin_token_is_a_403_not_a_crash(monkeypatch):
    monkeypatch.setenv("RP_ADMIN_TOKEN", "an-admin-token-for-tests")
    response = client.post(
        "/stocks/ingest",
        json={},
        headers={"Authorization": "Bearer café".encode("utf-8")},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "value",
    ["", "not base64!", base64.b64encode(b"short").decode()],
    ids=["empty", "invalid", "too-short"],
)
def test_unusable_jwt_secrets_are_treated_as_unset(monkeypatch, value):
    monkeypatch.setenv("RP_FASTAPI_JWT_SECRET", value)
    assert dependency.jwt_secret_bytes() is None


def test_a_full_size_jwt_secret_is_used(monkeypatch):
    key = os.urandom(64)
    monkeypatch.setenv("RP_FASTAPI_JWT_SECRET", base64.b64encode(key).decode() + "\n")
    assert dependency.jwt_secret_bytes() == key


def test_startup_reports_missing_configuration(monkeypatch, caplog):
    monkeypatch.delenv("RP_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("RP_FASTAPI_JWT_SECRET", "")
    with caplog.at_level(logging.ERROR):
        with TestClient(app):
            pass
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any(m.startswith("Startup check:") and "RP_ADMIN_TOKEN" in m for m in messages)
    assert any(m.startswith("Startup check:") and "JWT secret" in m for m in messages)


@pytest.mark.parametrize(
    "value,expected",
    [("", False), ("0", False), ("false", False), ("off", False), ("1", True), ("true", True)],
)
def test_debug_parses_as_a_flag(monkeypatch, value, expected):
    monkeypatch.setenv("DEBUG", value)
    assert Settings().debug is expected


def test_stocks_metrics_may_be_null():
    payload = IngestRunMeta.model_validate(
        {
            "as_of_date": "2026-11-07",
            "universe_size": 500,
            "n_events": 10,
            "start_date": "2020-01-01",
            "end_date": "2026-11-06",
            "run_timestamp_utc": "2026-11-07T12:00:00Z",
            "metrics": {"sharpe": 1.2, "ic": None},
        }
    )
    assert payload.metrics["ic"] is None

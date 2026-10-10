"""Checks for the production defaults: no public docs, a narrow CORS policy,
and a JWT gate that only takes AuthAPI access tokens."""
import asyncio
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("RP_FASTAPI_API_KEY", "test-key-for-ci-only")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.dependency import has_access  # noqa: E402
from src.main import app  # noqa: E402

client = TestClient(app)
SECRET = base64.b64encode(os.urandom(48)).decode()
ORIGIN = "http://localhost:4200"


def test_docs_are_off_outside_debug():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_cors_allows_the_api_key_but_no_credentials():
    response = client.options(
        "/stats/sample",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in response.headers


def test_cors_refuses_other_headers_and_methods():
    response = client.options(
        "/stats/sample",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 400


def _token(**claims) -> str:
    body = {"sub": "someone", "exp": int(time.time()) + 60, **claims}
    return jwt.encode(body, base64.b64decode(SECRET), algorithm="HS256")


def _check(token: str):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(has_access(credentials))


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("RP_FASTAPI_JWT_SECRET", SECRET)


def test_access_tokens_pass():
    assert _check(_token(typ="access"))["sub"] == "someone"


@pytest.mark.parametrize(
    "token",
    [
        _token(typ="refresh"),
        _token(),
        _token(typ="access", exp=int(time.time()) - 60),
        jwt.encode({"sub": "someone", "typ": "access", "exp": int(time.time()) + 60},
                   b"some-other-key-that-is-long-enough!!", algorithm="HS256"),
        "not-a-jwt",
    ],
    ids=["refresh", "untyped", "expired", "wrong-key", "garbage"],
)
def test_everything_else_gets_a_fixed_401(token):
    with pytest.raises(HTTPException) as caught:
        _check(token)
    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid or expired token"

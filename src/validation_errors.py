"""422 responses that can always be rendered.

FastAPI's default handler echoes each invalid input back. JSON has no
Infinity or NaN, so a body like {"std": Infinity} (which Python's parser
accepts) made rendering the 422 itself fail with a 500. Non-finite numbers are
sent back as strings instead; everything else matches the default response.
"""
import math

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": _finite(jsonable_encoder(exc.errors()))},
    )

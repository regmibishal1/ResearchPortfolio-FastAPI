"""Request body size cap.

FastAPI reads and parses a JSON body before the router's auth dependencies
run, so without a cap anyone could make the worker parse an arbitrarily large
body without a key or token. This ASGI middleware rejects an oversized body
with 413 before the app sees it: at once when Content-Length says so, or as
soon as a streamed body passes the limit.
"""
from fastapi import HTTPException
from starlette.responses import JSONResponse

# The pipelines push a few hundred KB at most (a World Cup snapshot is about
# 64 KB); everything else is a small form or sampler request.
INGEST_PATHS = {"/worldcup/ingest", "/stocks/ingest"}
INGEST_LIMIT = 8 * 1024 * 1024
DEFAULT_LIMIT = 64 * 1024

BODY_METHODS = {"POST", "PUT", "PATCH"}


def limit_for(path: str) -> int:
    return INGEST_LIMIT if path in INGEST_PATHS else DEFAULT_LIMIT


def _too_large() -> JSONResponse:
    return JSONResponse({"detail": "Request body too large"}, status_code=413)


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await _too_large()(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI passes an HTTPException from body reading
                    # straight through, so this becomes the 413.
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except HTTPException as exc:
            if exc.status_code != 413 or started:
                raise
            await _too_large()(scope, receive, send)

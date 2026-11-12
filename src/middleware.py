"""
HTTP request/response logging middleware.

Responsibilities:
  - Assign a short unique request ID to each request
  - Extract the real client IP, from CF-Connecting-IP or else the socket
  - Store both in ContextVars so all downstream loggers see them automatically
  - Log the incoming request and the outgoing response with elapsed time
  - Return X-Request-ID in the response header for end-to-end tracing
"""
import logging
import time
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src import request_stats
from src.logging_config import client_ip_var, request_id_var

logger = logging.getLogger(__name__)

# Health checks are polled frequently; log them at DEBUG to keep production
# output clean. Flip to logging.INFO if you need to audit liveness traffic.
_HEALTH_LOG_LEVEL = logging.DEBUG


# Route templates are short; the cap only guards the stats table.
_MAX_ROUTE_LENGTH = 200


def _route_of(request: Request) -> str:
    """
    The route as a template ("/stocks/company/{ticker}"), so counts never key
    on raw values. The matched route's own path leaves out its router prefix,
    so the prefix is what the decoded request path has in front of the route
    filled in with its parameters. Prefixes are fixed strings, never caller
    input; anything that does not line up counts as "unmatched".
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    path_format = getattr(route, "path_format", None)
    if not isinstance(template, str) or not isinstance(path_format, str):
        return "unmatched"
    try:
        filled = path_format.format(**{k: str(v) for k, v in request.path_params.items()})
    except (KeyError, IndexError, ValueError):
        return "unmatched"
    full_path = request.scope.get("path", "")
    if not full_path.endswith(filled):
        return "unmatched"
    prefix = full_path[: len(full_path) - len(filled)]
    return (prefix + template)[:_MAX_ROUTE_LENGTH]


def _get_client_ip(request: Request) -> str:
    """
    Resolve the real originating IP for a request.

    Priority:
      1. CF-Connecting-IP, set by Cloudflare Tunnel, which overwrites any
         value the visitor sent.
      2. Socket remote host, for direct connections (local dev, the LAN
         port). X-Forwarded-For is not used: any caller can set it.
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware that provides structured, request-scoped logging.

    Each request gets:
      - A 12-character hex request ID (e.g. "a3f9c1d20b44")
      - The real client IP extracted via _get_client_ip()
      - An incoming log line:  > METHOD /path
      - An outgoing log line:  < STATUS METHOD /path  elapsed_ms
      - X-Request-ID response header for correlation in browser / downstream logs

    Log levels for outgoing lines:
      - DEBUG   : /health endpoint (noisy health-check polling)
      - INFO    : 1xx / 2xx / 3xx responses
      - WARNING : 4xx responses
      - ERROR   : 5xx responses or unhandled exceptions
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = uuid.uuid4().hex[:12]
        client_ip = _get_client_ip(request)

        # Populate ContextVars, visible to all loggers in this async task
        request_id_var.set(req_id)
        client_ip_var.set(client_ip)

        path = request.url.path
        is_health = path == "/health"
        in_level = _HEALTH_LOG_LEVEL if is_health else logging.INFO

        logger.log(in_level, "> %s %s", request.method, path)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception(
                "Unhandled exception | %s %s | %.1fms",
                request.method,
                path,
                elapsed,
            )
            if not is_health:
                await run_in_threadpool(
                    request_stats.record, request.method, _route_of(request), 500, elapsed, req_id
                )
            raise

        elapsed = (time.perf_counter() - start) * 1000

        if response.status_code >= 500:
            out_level = logging.ERROR
        elif response.status_code >= 400:
            out_level = logging.WARNING
        else:
            out_level = in_level  # keep health checks at DEBUG

        logger.log(
            out_level,
            "< %d %s %s %.1fms",
            response.status_code,
            request.method,
            path,
            elapsed,
        )

        # Counted for the admin dashboard; health probes would drown everything else.
        if not is_health and request.method != "OPTIONS":
            await run_in_threadpool(
                request_stats.record,
                request.method,
                _route_of(request),
                response.status_code,
                elapsed,
                req_id,
            )

        # Echo the request ID so clients can correlate browser logs with server logs
        response.headers["X-Request-ID"] = req_id
        return response

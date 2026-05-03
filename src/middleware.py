"""
HTTP request/response logging middleware.

Responsibilities:
  - Assign a short unique request ID to each request
  - Extract the real client IP (CF-Connecting-IP → X-Forwarded-For → socket)
  - Store both in ContextVars so all downstream loggers see them automatically
  - Log the incoming request and the outgoing response with elapsed time
  - Return X-Request-ID in the response header for end-to-end tracing
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.logging_config import client_ip_var, request_id_var

logger = logging.getLogger(__name__)

# Health checks are polled frequently; log them at DEBUG to keep production
# output clean. Flip to logging.INFO if you need to audit liveness traffic.
_HEALTH_LOG_LEVEL = logging.DEBUG


def _get_client_ip(request: Request) -> str:
    """
    Resolve the real originating IP for a request.

    Priority:
      1. CF-Connecting-IP  — set by Cloudflare Tunnel; cannot be spoofed
         because the Tunnel terminates TLS before passing the request to us.
      2. X-Forwarded-For   — leftmost entry, used as fallback for local dev
         traffic that doesn't go through Cloudflare.
      3. Socket remote host — last-resort fallback (local direct connections).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware that provides structured, request-scoped logging.

    Each request gets:
      - A 12-character hex request ID (e.g. "a3f9c1d20b44")
      - The real client IP extracted via _get_client_ip()
      - An incoming log line:  → METHOD /path
      - An outgoing log line:  ← STATUS METHOD /path  elapsed_ms
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

        # Populate ContextVars — visible to all loggers in this async task
        request_id_var.set(req_id)
        client_ip_var.set(client_ip)

        path = request.url.path
        is_health = path == "/health"
        in_level = _HEALTH_LOG_LEVEL if is_health else logging.INFO

        logger.log(in_level, "→ %s %s", request.method, path)

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
            "← %d %s %s %.1fms",
            response.status_code,
            request.method,
            path,
            elapsed,
        )

        # Echo the request ID so clients can correlate browser logs with server logs
        response.headers["X-Request-ID"] = req_id
        return response

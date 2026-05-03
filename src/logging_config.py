"""
Logging configuration for the ResearchPortfolio FastAPI server.

Sets up a single root handler that injects per-request context
(request_id, client_ip) into every log line via ContextVars.
Call setup_logging() once at application startup.
"""
import logging
import sys
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# Per-request context — populated by RequestLoggingMiddleware on each request.
# ContextVar is async-safe: each asyncio Task gets its own copy.
# ---------------------------------------------------------------------------
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="-")


class ContextFormatter(logging.Formatter):
    """
    Logging formatter that injects the current request_id and client_ip
    from ContextVars into every log record before formatting.
    Falls back to "-" outside of a request context (e.g. startup logs).
    """

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get("-")  # type: ignore[attr-defined]
        record.client_ip = client_ip_var.get("-")  # type: ignore[attr-defined]
        return super().format(record)


_FMT = (
    "%(asctime)s | %(levelname)-8s"
    " | req=%(request_id)s"
    " | ip=%(client_ip)-15s"
    " | %(name)s"
    " | %(message)s"
)
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger with the context-aware formatter.
    Should be called exactly once before the FastAPI app is created.

    Args:
        level: Root log level (e.g. logging.DEBUG, logging.INFO).
               Defaults to INFO; set DEBUG via the DEBUG env var.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ContextFormatter(_FMT, datefmt=_DATE_FMT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Suppress uvicorn's built-in access log — we produce our own via
    # RequestLoggingMiddleware so double-logging would be confusing.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False

    # Keep uvicorn startup/shutdown messages at INFO but silence httpx noise.
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

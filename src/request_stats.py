"""Request counts and recent server errors for the admin dashboard.

Gunicorn runs several workers, so the numbers live in a small SQLite file
they all share rather than in one worker's memory. The file sits in the
system temp folder, so a container restart starts the counts again.

Only the method, the route, the status, the time taken and the request id
are kept: never bodies, query strings, headers, tokens or client IPs.
Recording never fails a request; a stats error is swallowed.
"""
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

DB_PATH = Path(
    os.getenv("RP_REQUEST_STATS_PATH")
    or Path(tempfile.gettempdir()) / "rp-request-stats.sqlite3"
)
KEEP_SECONDS = 7 * 24 * 3600
KEEP_ERRORS = 100

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_last_cleanup = 0.0


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=2, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS counts ("
            " minute INTEGER NOT NULL, route TEXT NOT NULL, status_class INTEGER NOT NULL,"
            " n INTEGER NOT NULL, PRIMARY KEY (minute, route, status_class))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS errors ("
            " at REAL NOT NULL, method TEXT NOT NULL, route TEXT NOT NULL,"
            " status INTEGER NOT NULL, ms REAL NOT NULL, request_id TEXT NOT NULL)"
        )
        _conn = conn
    return _conn


def record(method: str, route: str, status: int, ms: float, request_id: str, now: float | None = None) -> None:
    """Counts one request; keeps the details of a 5xx."""
    global _last_cleanup
    now = time.time() if now is None else now
    minute = int(now // 60)
    try:
        with _lock:
            conn = _connect()
            conn.execute(
                "INSERT INTO counts VALUES (?, ?, ?, 1) "
                "ON CONFLICT (minute, route, status_class) DO UPDATE SET n = n + 1",
                (minute, route, status // 100),
            )
            if status >= 500:
                conn.execute(
                    "INSERT INTO errors VALUES (?, ?, ?, ?, ?, ?)",
                    (now, method, route, status, round(ms, 1), request_id),
                )
                conn.execute(
                    "DELETE FROM errors WHERE rowid NOT IN "
                    "(SELECT rowid FROM errors ORDER BY at DESC LIMIT ?)",
                    (KEEP_ERRORS,),
                )
            # Dropping what is older than a week once an hour is plenty.
            if now - _last_cleanup > 3600:
                conn.execute("DELETE FROM counts WHERE minute < ?", (minute - KEEP_SECONDS // 60,))
                _last_cleanup = now
    except sqlite3.Error:
        pass


def summary(now: float | None = None) -> dict:
    """Totals for the last hour and day, an hourly series, busiest routes and recent errors."""
    now = time.time() if now is None else now
    minute = int(now // 60)
    hour_ago, day_ago = minute - 60, minute - 24 * 60
    with _lock:
        conn = _connect()

        def by_class(since: int) -> dict[str, int]:
            rows = conn.execute(
                "SELECT status_class, SUM(n) FROM counts WHERE minute > ? GROUP BY status_class",
                (since,),
            ).fetchall()
            totals = {f"{c}xx": 0 for c in (2, 3, 4, 5)}
            for status_class, n in rows:
                key = f"{status_class}xx"
                if key in totals:
                    totals[key] = n
            return totals

        hourly = []
        for h in range(23, -1, -1):
            end = minute - h * 60
            rows = dict(conn.execute(
                "SELECT status_class, SUM(n) FROM counts WHERE minute > ? AND minute <= ? GROUP BY status_class",
                (end - 60, end),
            ).fetchall())
            hourly.append({
                "hour_start": (end - 60 + 1) * 60,
                "ok": rows.get(2, 0) + rows.get(3, 0),
                "client_errors": rows.get(4, 0),
                "server_errors": rows.get(5, 0),
            })
        routes = conn.execute(
            "SELECT route, SUM(n) AS total, SUM(CASE WHEN status_class = 5 THEN n ELSE 0 END) "
            "FROM counts WHERE minute > ? GROUP BY route ORDER BY total DESC LIMIT 10",
            (day_ago,),
        ).fetchall()
        errors = conn.execute(
            "SELECT at, method, route, status, ms, request_id FROM errors ORDER BY at DESC LIMIT 20"
        ).fetchall()
        first = conn.execute("SELECT MIN(minute) FROM counts").fetchone()[0]

    return {
        "counting_since": first * 60 if first is not None else None,
        "last_hour": by_class(hour_ago),
        "last_day": by_class(day_ago),
        "hourly": hourly,
        "busiest_routes": [
            {"route": route, "requests": total, "server_errors": server_errors}
            for route, total, server_errors in routes
        ],
        "recent_errors": [
            {"at": at, "method": method, "route": route, "status": status, "ms": ms, "request_id": request_id}
            for at, method, route, status, ms, request_id in errors
        ],
    }

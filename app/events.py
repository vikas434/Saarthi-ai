"""Events behind the admin's Insights: request timings and errors, and model or voice fallbacks.

Two kinds, both without call text or emails:
- `request`: one per /api request, with its route template, status and time taken.
- `fallback`: something answered with the backup instead of the real service, e.g. the coach
  scoring offline after a model error, or the browser voice after ElevenLabs refused.

Recording never breaks the request it describes. Rows older than RETENTION_DAYS are pruned
on write, at most once per PRUNE_EVERY_SECONDS.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
PRUNE_EVERY_SECONDS = 3600
MAX_DETAIL_CHARS = 120
MAX_NAME_CHARS = 120
KINDS = frozenset({"request", "fallback"})

_prune_lock = threading.Lock()
_last_prune = 0.0


def reset_for_tests() -> None:
    global _last_prune
    with _prune_lock:
        _last_prune = 0.0


def _now() -> datetime:
    return datetime.now(UTC)


def record(
    kind: str,
    name: str,
    *,
    status: int | None = None,
    latency_ms: float | None = None,
    user_id: str | None = None,
    detail: str = "",
) -> None:
    """Store one event. Logs and carries on if the database refuses."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind: {kind}")
    try:
        with engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO events (created_at, kind, name, status, latency_ms, user_id, "
                    "detail) VALUES (:created_at, :kind, :name, :status, :latency_ms, :user_id, "
                    ":detail)"
                ),
                {
                    "created_at": _now().isoformat(timespec="seconds"),
                    "kind": kind,
                    "name": name[:MAX_NAME_CHARS],
                    "status": status,
                    "latency_ms": None if latency_ms is None else round(latency_ms, 1),
                    "user_id": user_id,
                    "detail": (detail or "")[:MAX_DETAIL_CHARS] or None,
                },
            )
        _maybe_prune()
    except Exception:
        logger.exception("could not record event %s %s", kind, name)


def fallback(name: str, exc: BaseException | str) -> None:
    """Record that `name` (e.g. "coach.turn") answered with its backup, and why (no message text)."""
    reason = exc if isinstance(exc, str) else type(exc).__name__
    record("fallback", name, detail=reason)


def prune(now: datetime | None = None) -> int:
    """Delete events older than RETENTION_DAYS; returns how many went."""
    cutoff = ((now or _now()) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with engine().begin() as conn:
        result = conn.execute(
            text("DELETE FROM events WHERE created_at < :cutoff"), {"cutoff": cutoff}
        )
    return int(result.rowcount or 0)


def _maybe_prune() -> None:
    global _last_prune
    now = time.monotonic()
    with _prune_lock:
        if _last_prune and now - _last_prune < PRUNE_EVERY_SECONDS:
            return
        _last_prune = now
    prune()


def since(start: datetime, kind: str | None = None) -> list[dict]:
    """Events from `start` on, oldest first."""
    sql = "SELECT created_at, kind, name, status, latency_ms, user_id, detail FROM events "
    sql += "WHERE created_at >= :start" + (" AND kind = :kind" if kind else "") + " ORDER BY id"
    params = {"start": start.isoformat(timespec="seconds"), "kind": kind}
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]

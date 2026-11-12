"""Token usage and cost of every model call. Prices come from config/pricing.json.

Routes say whose call it is with `attribute(session_id, user_id)`; coach code says what kind of
call it is with `kind("turn" | "report" | "survey" | "draft")`. The model client reports tokens
with `record_reply(model, reply_usage)`. Context travels with contextvars, so threads started
for the scorecard must run inside `contextvars.copy_context()`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import text

from app.config import CONFIG_DIR
from app.db import engine

logger = logging.getLogger(__name__)
MILLION = 1_000_000

_session_id: ContextVar[str | None] = ContextVar("usage_session_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("usage_user_id", default=None)
_kind: ContextVar[str] = ContextVar("usage_kind", default="other")


@lru_cache(maxsize=1)
def _prices() -> dict:
    return json.loads((CONFIG_DIR / "pricing.json").read_text(encoding="utf-8"))


def reset_for_tests() -> None:
    _prices.cache_clear()


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    table = _prices()
    p = table["models"].get(model, table["default"])
    return (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_read_tokens * p["cache_read"]
        + cache_write_tokens * p["cache_write"]
    ) / MILLION


@contextmanager
def attribute(*, session_id: str | None, user_id: str | None) -> Iterator[None]:
    tokens = (_session_id.set(session_id), _user_id.set(user_id))
    try:
        yield
    finally:
        _session_id.reset(tokens[0])
        _user_id.reset(tokens[1])


@contextmanager
def kind(name: str) -> Iterator[None]:
    token = _kind.set(name)
    try:
        yield
    finally:
        _kind.reset(token)


def _today_start() -> str:
    day = datetime.now(UTC).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC).isoformat(timespec="seconds")


def record(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    kind: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> float:
    """Store one model call's usage and return its cost in US dollars."""
    cost = cost_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    with engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usage (created_at, session_id, user_id, kind, model, input_tokens, "
                "output_tokens, cache_read_tokens, cache_write_tokens, cost_usd) VALUES "
                "(:created_at, :session_id, :user_id, :kind, :model, :input_tokens, "
                ":output_tokens, :cache_read_tokens, :cache_write_tokens, :cost_usd)"
            ),
            {
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "session_id": session_id if session_id is not None else _session_id.get(),
                "user_id": user_id if user_id is not None else _user_id.get(),
                "kind": kind or _kind.get(),
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cost_usd": cost,
            },
        )
    return cost


def record_reply(model: str, reply_usage: object | None) -> None:
    """Record the usage block of a model reply. Never breaks the call if recording fails."""
    if reply_usage is None:
        return
    try:
        record(
            model,
            int(getattr(reply_usage, "input_tokens", 0) or 0),
            int(getattr(reply_usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(reply_usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(reply_usage, "cache_creation_input_tokens", 0) or 0),
        )
    except Exception:  # usage must not break coaching; the error is logged
        logger.exception("could not record model usage")


def spend_today() -> float:
    with engine().connect() as conn:
        total = conn.execute(
            text("SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE created_at >= :start"),
            {"start": _today_start()},
        ).scalar_one()
    return float(total)


def rows_for_session(session_id: str) -> list[dict]:
    with engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT kind, model, user_id, input_tokens, output_tokens, cache_read_tokens, "
                "cache_write_tokens, cost_usd, created_at FROM usage "
                "WHERE session_id = :sid ORDER BY id"
            ),
            {"sid": session_id},
        ).mappings()
        return [dict(r) for r in rows]


def session_cost(session_id: str) -> float:
    return round(sum(r["cost_usd"] for r in rows_for_session(session_id)), 6)


def calls_today(user_id: str) -> int:
    with engine().connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM sessions WHERE user_id = :uid AND started_at >= :start"),
                {"uid": user_id, "start": _today_start()},
            ).scalar_one()
        )

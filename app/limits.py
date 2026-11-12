"""Limits that keep the demo cheap: a daily spend cap, calls per user per day, a rate limit.

All three come from env. The rate limit is kept in memory, which is right for one instance.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app import usage
from app.config import env

DEFAULT_DAILY_SPEND_CAP_USD = 0.50
DEFAULT_MAX_CALLS_PER_USER_PER_DAY = 20
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_MAX_REPLIES_PER_CALL = 14
WINDOW_SECONDS = 60.0

SPEND_LIMIT_MESSAGE = (
    "Daily limit reached: today's free practice is used up for everyone. "
    "New calls open again tomorrow at 05:30 IST (00:00 UTC)."
)
CALLS_LIMIT_TEMPLATE = (
    "Daily limit reached: you've had your {n} practice call{s} for today. "
    "Come back tomorrow for more (from 05:30 IST)."
)
RATE_LIMIT_MESSAGE = "Too many requests. Wait a few seconds and try again."


class LimitReached(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _float_env(name: str, default: float) -> float:
    try:
        return float(env(name) or default)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(env(name) or default)
    except ValueError:
        return default


def max_replies_per_call() -> int:
    return _int_env("MAX_REPLIES_PER_CALL", DEFAULT_MAX_REPLIES_PER_CALL)


def calls_per_day() -> int:
    return _int_env("MAX_CALLS_PER_USER_PER_DAY", DEFAULT_MAX_CALLS_PER_USER_PER_DAY)


def calls_left(user_id: str) -> int:
    return max(0, calls_per_day() - usage.calls_today(user_id))


def check_spend() -> None:
    """Raise LimitReached when today's model spend has reached the cap."""
    if usage.spend_today() >= _float_env("DAILY_SPEND_CAP_USD", DEFAULT_DAILY_SPEND_CAP_USD):
        raise LimitReached(SPEND_LIMIT_MESSAGE)


def check_new_call(user_id: str) -> None:
    """Raise LimitReached when a new practice call may not start."""
    check_spend()
    if calls_left(user_id) <= 0:
        n = calls_per_day()
        raise LimitReached(CALLS_LIMIT_TEMPLATE.format(n=n, s="" if n == 1 else "s"))


_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()


def check_rate(user_id: str) -> None:
    """Sliding one-minute window per user."""
    limit = _int_env("RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE)
    now = time.monotonic()
    with _lock:
        hits = _hits[user_id]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            raise LimitReached(RATE_LIMIT_MESSAGE)
        hits.append(now)

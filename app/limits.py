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
WINDOW_SECONDS = 60.0

SPEND_LIMIT_MESSAGE = (
    "Daily practice limit reached for today. New calls open again tomorrow (00:00 UTC)."
)
CALLS_LIMIT_MESSAGE = "Daily call limit reached for you. Please practise again tomorrow."
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


def check_new_call(user_id: str) -> None:
    """Raise LimitReached when a new practice call may not start."""
    if usage.spend_today() >= _float_env("DAILY_SPEND_CAP_USD", DEFAULT_DAILY_SPEND_CAP_USD):
        raise LimitReached(SPEND_LIMIT_MESSAGE)
    max_calls = _int_env("MAX_CALLS_PER_USER_PER_DAY", DEFAULT_MAX_CALLS_PER_USER_PER_DAY)
    if usage.calls_today(user_id) >= max_calls:
        raise LimitReached(CALLS_LIMIT_MESSAGE)


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

"""Sends firing alerts to Slack, at most once a day per alert. Off unless SLACK_WEBHOOK_URL is set.

The free host has no scheduled jobs, so alerts are checked when the admin opens Insights and
after API requests, at most once every CHECK_EVERY_SECONDS. Messages carry the alert's title and
reason only: no emails, names or call text.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

import httpx

from app import alerts, insights, store
from app.config import env

logger = logging.getLogger(__name__)

SLACK_HOST = "https://hooks.slack.com/"
CHECK_EVERY_SECONDS = 300
TIMEOUT_SECONDS = 5
SENT_KEY = "alert-sent:{id}"
LEVEL_ICONS = {"critical": ":red_circle:", "warning": ":large_orange_circle:"}

_lock = threading.Lock()
_last_check = 0.0


def reset_for_tests() -> None:
    global _last_check
    with _lock:
        _last_check = 0.0


def webhook_url() -> str:
    """The Slack incoming-webhook URL, or "" when unset or not a Slack webhook."""
    url = env("SLACK_WEBHOOK_URL")
    if url and not url.startswith(SLACK_HOST):
        logger.error("SLACK_WEBHOOK_URL ignored: it must start with %s", SLACK_HOST)
        return ""
    return url


def _message(alert: dict) -> str:
    icon = LEVEL_ICONS.get(alert["level"], ":large_orange_circle:")
    where = env("RENDER_SERVICE_NAME") or "Saarthi"
    return f"{icon} *{alert['title']}* ({where})\n{alert['reason']}"


def send_new(firing: list[dict], now: datetime | None = None) -> list[str]:
    """Post each alert not yet sent today; returns the ids sent. Never raises."""
    url = webhook_url()
    if not url or not firing:
        return []
    today = (now or datetime.now(UTC)).date().isoformat()
    sent = []
    for alert in firing:
        key = SENT_KEY.format(id=alert["id"])
        try:
            if store.get_kv(key) == today:
                continue
            res = httpx.post(url, json={"text": _message(alert)}, timeout=TIMEOUT_SECONDS)
            if res.status_code != 200:
                logger.warning("Slack refused alert %s: %s", alert["id"], res.status_code)
                continue
            store.set_kv(key, today)
            sent.append(alert["id"])
        except Exception as exc:  # noqa: BLE001 - alerts must never break the app
            logger.warning("could not send alert %s: %s", alert["id"], type(exc).__name__)
    return sent


def firing_now(now: datetime | None = None) -> list[dict]:
    """The alerts firing right now, worked out from scratch."""
    now = now or datetime.now(UTC)
    engineering = insights.engineering(1, now)
    return alerts.evaluate(
        spend=engineering["spend"],
        voice_budget=engineering["voice_budget"],
        day=insights.last_24h(now),
        last_call_at=insights.business(1, now)["last_call_at"],
        now=now,
    )


def maybe_check() -> list[str]:
    """After a request: check alerts and send new ones, at most every CHECK_EVERY_SECONDS."""
    global _last_check
    if not webhook_url():
        return []
    stamp = time.monotonic()
    with _lock:
        if _last_check and stamp - _last_check < CHECK_EVERY_SECONDS:
            return []
        _last_check = stamp
    try:
        return send_new(firing_now())
    except Exception:
        logger.exception("alert check failed")
        return []

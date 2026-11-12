"""Alerts for the admin: plain-English warnings worked out from Insights numbers.

Thresholds live in config/alerts.json. Each alert says what is wrong, the number behind it and
what it is compared with, so the admin can act without opening a log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache

from app.config import CONFIG_DIR

DEFAULTS = {
    "spend_cap_pct": 80,
    "voice_cap_pct": 80,
    "fallback_pct_24h": 10,
    "fallback_min_calls_24h": 5,
    "p95_reply_seconds": 8,
    "p95_min_replies_24h": 5,
    "error_pct_24h": 2,
    "error_min_requests_24h": 20,
    "quiet_days": 3,
}


@lru_cache(maxsize=1)
def thresholds() -> dict:
    path = CONFIG_DIR / "alerts.json"
    loaded = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**DEFAULTS, **{k: v for k, v in loaded.items() if k in DEFAULTS}}


def reset_for_tests() -> None:
    thresholds.cache_clear()


def _alert(aid: str, level: str, title: str, reason: str, value: float, limit: float) -> dict:
    return {
        "id": aid,
        "level": level,
        "title": title,
        "reason": reason,
        "value": value,
        "threshold": limit,
    }


def _spend(spend: dict, t: dict) -> list[dict]:
    cap = spend["daily_cap_usd"]
    if not cap:
        return []
    pct = round(100 * spend["today_usd"] / cap, 1)
    if pct < t["spend_cap_pct"]:
        return []
    full = pct >= 100
    return [
        _alert(
            "spend",
            "critical" if full else "warning",
            "Daily spend cap reached" if full else "Daily spend is close to the cap",
            f"${spend['today_usd']:.2f} of the ${cap:.2f} daily cap is used ({pct:g}%). "
            + (
                "New calls are blocked until 00:00 UTC."
                if full
                else "New calls stop when it reaches 100%."
            ),
            pct,
            t["spend_cap_pct"],
        )
    ]


def _voice(budget: dict, t: dict) -> list[dict]:
    cap = budget["monthly_cap"]
    if not cap or not budget["chars_this_month"]:
        return []
    pct = round(100 * budget["chars_this_month"] / cap, 1)
    if pct < t["voice_cap_pct"]:
        return []
    return [
        _alert(
            "voice",
            "warning",
            "Human voice budget is running out",
            f"{budget['chars_this_month']:,} of {cap:,} ElevenLabs characters are used this month "
            f"({pct:g}%). After that customers speak with the browser voice.",
            pct,
            t["voice_cap_pct"],
        )
    ]


def _health(day: dict, t: dict) -> list[dict]:
    out = []
    fb = day["fallbacks"]
    if (
        fb["model_calls"] >= t["fallback_min_calls_24h"]
        and (fb["model_fallback_pct"] or 0) > t["fallback_pct_24h"]
    ):
        out.append(
            _alert(
                "fallback",
                "critical",
                "The AI model is failing",
                f"{fb['model_fallbacks']} of {fb['model_calls']} model calls in the last 24 hours "
                f"used the offline backup ({fb['model_fallback_pct']:g}%). Check the model key, "
                "credit and the provider's status.",
                fb["model_fallback_pct"],
                t["fallback_pct_24h"],
            )
        )
    reply = day["reply"]
    limit_ms = t["p95_reply_seconds"] * 1000
    if reply["count"] >= t["p95_min_replies_24h"] and (reply["p95_ms"] or 0) > limit_ms:
        seconds = round(reply["p95_ms"] / 1000, 1)
        out.append(
            _alert(
                "slow_replies",
                "warning",
                "Customer replies are slow",
                f"1 in 20 replies took longer than {seconds:g} s in the last 24 hours "
                f"(target: under {t['p95_reply_seconds']:g} s).",
                seconds,
                t["p95_reply_seconds"],
            )
        )
    if (
        day["requests"] >= t["error_min_requests_24h"]
        and (day["error_pct"] or 0) > t["error_pct_24h"]
    ):
        out.append(
            _alert(
                "errors",
                "critical",
                "Server errors are high",
                f"{day['errors']} of {day['requests']} requests failed in the last 24 hours "
                f"({day['error_pct']:g}%). Check the host's logs.",
                day["error_pct"],
                t["error_pct_24h"],
            )
        )
    return out


def _quiet(last_call_at: str | None, now: datetime, t: dict) -> list[dict]:
    if last_call_at is None:
        return []
    idle = (now - datetime.fromisoformat(last_call_at)).total_seconds() / 86400
    if idle < t["quiet_days"]:
        return []
    return [
        _alert(
            "quiet",
            "warning",
            "Nobody has practised lately",
            f"The last practice call was {int(idle)} days ago. Consider nudging the team.",
            round(idle, 1),
            t["quiet_days"],
        )
    ]


def evaluate(
    *,
    spend: dict,
    voice_budget: dict,
    day: dict,
    last_call_at: str | None,
    now: datetime | None = None,
) -> list[dict]:
    """Every alert that is firing now, most serious first."""
    t = thresholds()
    found = (
        _spend(spend, t)
        + _health(day, t)
        + _voice(voice_budget, t)
        + _quiet(last_call_at, now or datetime.now(UTC), t)
    )
    return sorted(found, key=lambda a: a["level"] != "critical")

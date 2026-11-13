"""Numbers for the admin's Insights: adoption, feature use, outcomes, cost, and service health.

Counts and rates only: no emails, names or call text leave this module. Everything is worked out
from `sessions`, `turns`, `usage` and `events` at read time, so it works offline too.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import text

from app import coach, events, limits, voice
from app.db import engine

WINDOWS = (7, 30)
TOP_SCENARIOS = 5
TURN_ROUTE = "POST /api/sessions/{sid}/turns"
REPORT_ROUTE = "POST /api/sessions/{sid}/end"
VOICE_ROUTE = "GET /api/sessions/{sid}/voice/{idx}"
AVATAR_ROUTE = "POST /api/sessions/{sid}/avatar"
DRAFT_ROUTE = "POST /api/roleplays/draft"
SAVE_ROLEPLAY_ROUTE = "POST /api/roleplays"
MODEL_KINDS = ("turn", "report", "survey", "tutor", "draft")
SCORE_STEP = 5  # "first call to fifth call"


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _day(stamp: str) -> date:
    return datetime.fromisoformat(stamp).date()


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceiling
    return ordered[int(rank) - 1]


# ---- loading -------------------------------------------------------------------------------


def _sessions() -> list[dict]:
    """Every signed-in person's session, oldest first (scripted evals have no user)."""
    sql = (
        "SELECT id, user_id, scenario_id, kind, started_at, score, "
        "CASE WHEN report IS NULL THEN 0 ELSE 1 END AS finished "
        "FROM sessions WHERE user_id IS NOT NULL ORDER BY started_at"
    )
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings()]


def _spoken_replies(start: datetime) -> int:
    sql = (
        "SELECT COUNT(*) FROM turns t JOIN sessions s ON s.id = t.session_id "
        "WHERE t.agent_seconds IS NOT NULL AND s.started_at >= :start AND s.user_id IS NOT NULL"
    )
    with engine().connect() as conn:
        return int(conn.execute(text(sql), {"start": _iso(start)}).scalar_one())


def _usage(start: datetime) -> list[dict]:
    sql = "SELECT created_at, kind, cost_usd FROM usage WHERE created_at >= :start"
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), {"start": _iso(start)}).mappings()]


# ---- business ------------------------------------------------------------------------------


def _activity(sessions: list[dict], requests: list[dict]) -> dict[str, set[date]]:
    """Days each person was active: started a session or used the API while signed in."""
    days: dict[str, set[date]] = defaultdict(set)
    for s in sessions:
        days[s["user_id"]].add(_day(s["started_at"]))
    for r in requests:
        if r["user_id"]:
            days[r["user_id"]].add(_day(r["created_at"]))
    return days


def _adoption(activity: dict[str, set[date]], start: date, today: date) -> dict:
    in_window = {u: {d for d in ds if d >= start} for u, ds in activity.items()}
    active = {u for u, ds in in_window.items() if ds}
    first_seen = {u: min(ds) for u, ds in activity.items() if ds}
    new = {u for u in active if first_seen[u] >= start}
    week_ago = today - timedelta(days=6)
    cohort = [u for u, first in first_seen.items() if start <= first <= today - timedelta(days=7)]
    came_back = [u for u in cohort if any(7 <= (d - first_seen[u]).days <= 13 for d in activity[u])]
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    return {
        "active_users": len(active),
        "weekly_active_users": sum(1 for ds in activity.values() if any(d >= week_ago for d in ds)),
        "new_users": len(new),
        "returning_users": len(active - new),
        "active_on_2plus_days_pct": _pct(
            sum(1 for u in active if len(in_window[u]) > 1), len(active)
        ),
        "second_week_return_pct": _pct(len(came_back), len(cohort)),
        "second_week_cohort": len(cohort),
        "daily_active": [
            {"day": d.isoformat(), "users": sum(1 for ds in activity.values() if d in ds)}
            for d in days
        ],
    }


def _funnel(sessions: list[dict], active: int, start: str) -> list[dict]:
    calls = [s for s in sessions if s["kind"] == "roleplay"]
    started = {s["user_id"] for s in calls if s["started_at"] >= start}
    finished = {s["user_id"] for s in calls if s["started_at"] >= start and s["finished"]}
    finished_ever = Counter(s["user_id"] for s in calls if s["finished"])
    second = {u for u in finished if finished_ever[u] >= 2}
    steps = [
        ("Signed in", max(active, len(started))),
        ("Started a call", len(started)),
        ("Finished a call", len(finished)),
        ("Did a second call", len(second)),
    ]
    top = steps[0][1]
    return [{"step": name, "users": n, "pct": _pct(n, top)} for name, n in steps]


def _features(sessions: list[dict], requests: list[dict], start: datetime) -> list[dict]:
    begin = _iso(start)
    recent = [s for s in sessions if s["started_at"] >= begin]

    def by_route(route: str, ok: tuple[int, ...] = (200,)) -> tuple[int, int]:
        hits = [r for r in requests if r["name"] == route and r["status"] in ok]
        return len(hits), len({r["user_id"] for r in hits if r["user_id"]})

    def by_kind(kind: str) -> tuple[int, int]:
        rows = [s for s in recent if s["kind"] == kind]
        return len(rows), len({s["user_id"] for s in rows})

    rows = [
        ("Practice calls", *by_kind("roleplay")),
        ("Tutor lessons", *by_kind("tutor")),
        ("AI roleplay drafts", *by_route(DRAFT_ROUTE)),
        ("Roleplays saved", *by_route(SAVE_ROLEPLAY_ROUTE)),
        ("Human voice lines", *by_route(VOICE_ROUTE)),
        ("Video customer calls", *by_route(AVATAR_ROUTE)),
        ("Spoken replies", _spoken_replies(start), None),
    ]
    return [{"feature": name, "uses": uses, "users": users} for name, uses, users in rows]


def _top_scenarios(sessions: list[dict], start: str) -> list[dict]:
    calls = [s for s in sessions if s["kind"] == "roleplay" and s["started_at"] >= start]
    titles = {s["id"]: s.get("title", s["id"]) for s in coach.load_scenarios()}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for s in calls:
        grouped[s["scenario_id"]].append(s)
    ranked = sorted(grouped.items(), key=lambda kv: -len(kv[1]))[:TOP_SCENARIOS]
    out = []
    for sid, rows in ranked:
        scores = [r["score"] for r in rows if r["finished"] and r["score"] is not None]
        out.append(
            {
                "scenario": titles.get(sid, "A deleted roleplay"),
                "calls": len(rows),
                "finished": sum(1 for r in rows if r["finished"]),
                "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            }
        )
    return out


def _score_change(sessions: list[dict]) -> dict:
    """Average change from each person's first scored call to their fifth (and to their latest)."""
    scored: dict[str, list[float]] = defaultdict(list)
    for s in sessions:
        if s["kind"] == "roleplay" and s["finished"] and s["score"] is not None:
            scored[s["user_id"]].append(float(s["score"]))
    fifth = [v[SCORE_STEP - 1] - v[0] for v in scored.values() if len(v) >= SCORE_STEP]
    latest = [v[-1] - v[0] for v in scored.values() if len(v) >= 2]
    by_call = []
    for n in range(SCORE_STEP):
        at_n = [v[n] for v in scored.values() if len(v) > n]
        by_call.append(
            {
                "call": n + 1,
                "avg_score": round(sum(at_n) / len(at_n), 1) if at_n else None,
                "users": len(at_n),
            }
        )
    return {
        "first_to_fifth": round(sum(fifth) / len(fifth), 1) if fifth else None,
        "first_to_fifth_users": len(fifth),
        "first_to_latest": round(sum(latest) / len(latest), 1) if latest else None,
        "first_to_latest_users": len(latest),
        "by_call": by_call,
    }


def _cost(usage_rows: list[dict], active: int, finished_calls: int) -> dict:
    total = sum(r["cost_usd"] for r in usage_rows)
    return {
        "total_usd": round(total, 4),
        "per_active_user_usd": round(total / active, 4) if active else None,
        "per_finished_call_usd": round(total / finished_calls, 4) if finished_calls else None,
    }


def business(days: int, now: datetime | None = None, exclude: frozenset[str] = frozenset()) -> dict:
    """Adoption and outcomes. `exclude` leaves out people such as the admin looking at this."""
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    begin = _iso(start)
    sessions = [s for s in _sessions() if s["user_id"] not in exclude]
    requests = [r for r in events.since(start, "request") if r["user_id"] not in exclude]
    activity = _activity(sessions, requests)
    adoption = _adoption(activity, start.date(), now.date())
    finished = sum(
        1
        for s in sessions
        if s["kind"] == "roleplay" and s["finished"] and s["started_at"] >= begin
    )
    return {
        **adoption,
        "funnel": _funnel(sessions, adoption["active_users"], begin),
        "features": _features(sessions, requests, start),
        "top_scenarios": _top_scenarios(sessions, begin),
        "scores": _score_change(sessions),
        "cost": _cost(_usage(start), adoption["active_users"], finished),
        "last_call_at": next(
            (s["started_at"] for s in reversed(sessions) if s["kind"] == "roleplay"), None
        ),
    }


# ---- engineering ---------------------------------------------------------------------------


def _latency(requests: list[dict], route: str) -> dict:
    ms = [r["latency_ms"] for r in requests if r["name"] == route and r["latency_ms"] is not None]
    return {
        "count": len(ms),
        "p50_ms": round(median(ms)) if ms else None,
        "p95_ms": round(percentile(ms, 95)) if ms else None,
    }


def _fallbacks(fallback_rows: list[dict], usage_rows: list[dict]) -> dict:
    model_fb = [f for f in fallback_rows if not f["name"].startswith("voice.")]
    model_ok = sum(1 for u in usage_rows if u["kind"] in MODEL_KINDS)
    return {
        "model_fallbacks": len(model_fb),
        "model_calls": model_ok + len(model_fb),
        "model_fallback_pct": _pct(len(model_fb), model_ok + len(model_fb)),
        "voice_fallbacks": len(fallback_rows) - len(model_fb),
        "by_name": [
            {"name": n, "count": c}
            for n, c in Counter(f["name"] for f in fallback_rows).most_common()
        ],
    }


def _requests_by_day(requests: list[dict], start: date, today: date) -> list[dict]:
    out = []
    for i in range((today - start).days + 1):
        d = start + timedelta(days=i)
        rows = [r for r in requests if _day(r["created_at"]) == d]
        replies = [
            r["latency_ms"] for r in rows if r["name"] == TURN_ROUTE and r["latency_ms"] is not None
        ]
        out.append(
            {
                "day": d.isoformat(),
                "requests": len(rows),
                "errors": sum(1 for r in rows if (r["status"] or 0) >= 500),
                "reply_p95_ms": round(percentile(replies, 95)) if replies else None,
            }
        )
    return out


def health(requests: list[dict], fallback_rows: list[dict], usage_rows: list[dict]) -> dict:
    """Request, error, latency and fallback numbers for one stretch of events."""
    errors = [r for r in requests if (r["status"] or 0) >= 500]
    return {
        "requests": len(requests),
        "errors": len(errors),
        "error_pct": _pct(len(errors), len(requests)),
        "reply": _latency(requests, TURN_ROUTE),
        "scorecard": _latency(requests, REPORT_ROUTE),
        "voice": _latency(requests, VOICE_ROUTE),
        "fallbacks": _fallbacks(fallback_rows, usage_rows),
        "error_routes": [
            {"route": n, "count": c} for n, c in Counter(r["name"] for r in errors).most_common(5)
        ],
    }


def engineering(days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    requests = events.since(start, "request")
    voice_lines = [r for r in requests if r["name"] == VOICE_ROUTE and r["status"] in (200, 204)]
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spend_today = sum(r["cost_usd"] for r in _usage(today_start))
    return {
        **health(requests, events.since(start, "fallback"), _usage(start)),
        "by_day": _requests_by_day(requests, start.date(), now.date()),
        "voice_budget": {
            "provider": "elevenlabs" if voice.available() else "browser",
            "chars_this_month": voice.characters_this_month(),
            "monthly_cap": voice.monthly_cap(),
            "browser_voice_pct": _pct(
                sum(1 for r in voice_lines if r["status"] == 204), len(voice_lines)
            ),
        },
        "spend": {"today_usd": round(spend_today, 4), "daily_cap_usd": limits.daily_spend_cap()},
    }


def last_24h(now: datetime | None = None) -> dict:
    """Health over the last 24 hours, for alerts."""
    since = (now or datetime.now(UTC)) - timedelta(hours=24)
    return health(events.since(since, "request"), events.since(since, "fallback"), _usage(since))

"""Personal dashboard: chosen focus metrics over time, a practice streak, plain insights.

Every point comes from a scored roleplay call's report, so nothing here calls the model. The admin
also gets a team view: per person, calls and how their overall score moved.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from app import coach, store

MAX_FOCUS = 4
DEFAULT_FOCUS = ["overall", "filler_words", "questions", "talk_time"]
MAX_POINTS = 30
FOCUS_KEY = "focus:"
MARKER_PREFIX = "marker:"
GOOD_PERCENT_TARGET = 80
SURVEY_TARGET_SHARE = 0.8


def _analytic(metric_id: str, field: str) -> Callable[[dict], float | None]:
    def get(report: dict) -> float | None:
        for m in (report.get("analytics") or {}).get("metrics", []):
            if m["id"] == metric_id:
                return m.get(field)
        return None

    return get


def _overall(report: dict) -> float | None:
    if report.get("overall") is not None:
        return report["overall"]
    return coach.overall_score(report.get("markers", []))


# id: (name, unit, better, target, how to read it from a report)
ANALYTIC_METRICS: dict[str, tuple[str, str, str, float, Callable[[dict], float | None]]] = {
    "overall": ("Overall score", "%", "higher", 70, _overall),
    "filler_words": ("Filler words", "%", "lower", 3, _analytic("filler_words", "percent")),
    "weak_words": ("Weak words", "%", "lower", 3, _analytic("weak_words", "percent")),
    "questions": ("Questions asked", "", "higher", 3, _analytic("questions", "count")),
    "talk_time": ("Your talk time", "%", "lower", 50, _analytic("talk_time", "you_percent")),
    "pace": ("Pace", " wpm", "range", 140, _analytic("pace", "wpm")),
    "reply_length": (
        "Reply length",
        " words",
        "lower",
        40,
        _analytic("reply_length", "average_words"),
    ),
}


def _marker_reader(marker_id: str, survey: bool) -> Callable[[dict], float | None]:
    def get(report: dict) -> float | None:
        m = next((x for x in report.get("markers", []) if x["id"] == marker_id), None)
        if m is None:
            return None
        return m.get("score") if survey else m.get("percent")

    return get


def catalog() -> dict[str, dict]:
    """Every metric a person may focus on: delivery analytics, the overall score, each marker."""
    out = {
        mid: {
            "id": mid,
            "name": name,
            "unit": unit,
            "better": better,
            "target": target,
            "read": read,
        }
        for mid, (name, unit, better, target, read) in ANALYTIC_METRICS.items()
    }
    for m in coach.load_markers():
        survey = m["type"] == "survey"
        mid = MARKER_PREFIX + m["id"]
        out[mid] = {
            "id": mid,
            "name": m["name"],
            "unit": f" / {m['max']}" if survey else "%",
            "better": "higher",
            "target": round(m["max"] * SURVEY_TARGET_SHARE) if survey else GOOD_PERCENT_TARGET,
            "read": _marker_reader(m["id"], survey),
        }
    return out


def get_focus(user_id: str, known: dict[str, dict]) -> list[str]:
    saved = (store.get_kv(FOCUS_KEY + user_id) or "").split(",")
    focus = [m for m in saved if m in known][:MAX_FOCUS]
    return focus or list(DEFAULT_FOCUS)


def set_focus(user_id: str, metrics: list[str]) -> list[str]:
    known = catalog()
    if not 1 <= len(metrics) <= MAX_FOCUS or any(m not in known for m in metrics):
        raise ValueError(f"Choose 1 to {MAX_FOCUS} metrics from the list.")
    store.set_kv(FOCUS_KEY + user_id, ",".join(dict.fromkeys(metrics)))
    return get_focus(user_id, known)


def _day(stamp: str) -> date:
    return datetime.fromisoformat(stamp).astimezone(UTC).date()


def streak(days: set[date], today: date) -> int:
    """Consecutive practice days ending today, or yesterday if today has no practice yet."""
    current = today if today in days else today - timedelta(days=1)
    count = 0
    while current in days:
        count += 1
        current -= timedelta(days=1)
    return count


def _behavior_averages(reports: list[dict]) -> list[tuple[str, float]]:
    scores: dict[str, list[int]] = {}
    for r in reports:
        for m in r.get("markers", []):
            if m["type"] != "rubric" or m["id"] == "goals":
                continue
            for b in m.get("behaviors", []):
                if b.get("score"):
                    scores.setdefault(b["name"], []).append(b["score"])
    return sorted(((n, sum(v) / len(v)) for n, v in scores.items()), key=lambda x: x[1])


def insights(calls: list[dict]) -> list[str]:
    """Two or three plain sentences about the person's practice."""
    if not calls:
        return ["Finish a practice call to see your trends here."]
    reports = [c["report"] for c in calls]
    out = []
    overall = [v for v in (_overall(r) for r in reports) if v is not None]
    if len(overall) >= 2:
        verb = (
            "rose" if overall[-1] > overall[0] else "fell" if overall[-1] < overall[0] else "held"
        )
        out.append(
            f"Your overall score {verb} from {overall[0]}% to {overall[-1]}% "
            f"over {len(overall)} calls."
        )
    averages = _behavior_averages(reports)
    if len(averages) >= 2:
        (weak, w), (strong, s) = averages[0], averages[-1]
        out.append(f"Strongest: {strong} ({s:.1f} / 5). Work on: {weak} ({w:.1f} / 5).")
    latest = (reports[-1].get("analytics") or {}).get("metrics", [])
    fillers = next((m for m in latest if m["id"] == "filler_words"), None)
    starters = next((m for m in latest if m["id"] == "sentence_starters"), None)
    if fillers and fillers["top"]:
        out.append(f'Your most used filler word last call was "{fillers["top"][0]}".')
    elif starters and starters["verdict"] == "watch":
        out.append(f'{starters["percent"]}% of your sentences start with "{starters["word"]}".')
    return out[:3]


def for_user(user_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    known = catalog()
    calls = store.scored_calls(user_id)[-MAX_POINTS:]
    series = {
        mid: [
            {"at": c["ended_at"] or c["started_at"], "value": v}
            for c in calls
            if (v := m["read"](c["report"])) is not None
        ]
        for mid, m in known.items()
    }
    days = {_day(c["ended_at"] or c["started_at"]) for c in calls}
    week_start = now.date() - timedelta(days=6)
    return {
        "focus": get_focus(user_id, known),
        "catalog": [{k: v for k, v in m.items() if k != "read"} for m in known.values()],
        "series": series,
        "streak": streak(days, now.date()),
        "calls": len(calls),
        "calls_this_week": sum(
            1 for c in calls if _day(c["ended_at"] or c["started_at"]) >= week_start
        ),
        "insights": insights(calls),
    }


def team() -> list[dict]:
    """Per person: calls, last practice, and how the overall score moved. Most active first."""
    people: dict[str, list[dict]] = {}
    for c in store.scored_calls(None):
        people.setdefault(c["user_id"] or "unknown", []).append(c)
    rows = []
    for calls in people.values():
        scores = [v for v in (_overall(c["report"]) for c in calls) if v is not None]
        first, latest = (scores[0], scores[-1]) if scores else (None, None)
        rows.append(
            {
                "name": calls[-1]["agent_name"],
                "calls": len(calls),
                "last_active": calls[-1]["ended_at"] or calls[-1]["started_at"],
                "average": round(sum(scores) / len(scores)) if scores else None,
                "first": first,
                "latest": latest,
                "change": latest - first if scores else None,
            }
        )
    return sorted(rows, key=lambda r: (-r["calls"], r["name"]))

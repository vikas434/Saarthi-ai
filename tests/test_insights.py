"""Admin Insights: who uses TalkWise, what they use, whether it works, and the alerts."""

from datetime import UTC, datetime, timedelta

import pytest

from app import alerts, insights

SCENARIO = "price-worried-owner"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _s(user, day, *, kind="roleplay", finished=1, score=50.0, scenario=SCENARIO):
    return {
        "id": f"{user}-{day}-{kind}",
        "user_id": user,
        "scenario_id": scenario,
        "kind": kind,
        "started_at": (NOW - timedelta(days=day)).isoformat(timespec="seconds"),
        "score": score,
        "finished": finished,
    }


def test_percentile_is_nearest_rank():
    assert insights.percentile([], 95) is None
    assert insights.percentile([5.0], 95) == 5.0
    assert insights.percentile([float(i) for i in range(1, 101)], 95) == 95.0
    assert insights.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0


def test_adoption_counts_new_returning_and_second_week_return():
    today = NOW.date()
    activity = {
        "a": {today - timedelta(days=12), today - timedelta(days=3)},  # came back in week 2
        "b": {today - timedelta(days=10)},  # never came back
        "c": {today, today - timedelta(days=1)},  # new this week, two days
        "old": {today - timedelta(days=40)},
    }
    week = insights._adoption(activity, today - timedelta(days=6), today)
    assert week["active_users"] == 2  # a and c
    assert week["new_users"] == 1 and week["returning_users"] == 1
    assert week["active_on_2plus_days_pct"] == 50.0  # c, not a (one day in this week)
    month = insights._adoption(activity, today - timedelta(days=29), today)
    assert month["second_week_cohort"] == 2  # a and b first seen 7+ days ago
    assert month["second_week_return_pct"] == 50.0
    assert len(month["daily_active"]) == 30
    assert month["daily_active"][-1] == {"day": today.isoformat(), "users": 1}


def test_funnel_drops_off_step_by_step():
    sessions = [
        _s("a", 1),
        _s("a", 2),
        _s("b", 1, finished=0, score=None),
        _s("c", 1, kind="tutor"),
    ]
    start = (NOW - timedelta(days=6)).isoformat(timespec="seconds")
    funnel = insights._funnel(sessions, active=4, start=start)
    assert [f["users"] for f in funnel] == [4, 2, 1, 1]
    assert funnel[0]["pct"] == 100.0 and funnel[1]["pct"] == 50.0


def test_score_change_from_first_to_fifth_call():
    sessions = [_s("a", 10 - i, score=40.0 + 5 * i) for i in range(5)] + [
        _s("b", 3, score=60.0),
        _s("b", 2, score=50.0),
        _s("c", 1, kind="tutor", score=99.0),
    ]
    scores = insights._score_change(sessions)
    assert scores["first_to_fifth"] == 20.0 and scores["first_to_fifth_users"] == 1
    assert scores["first_to_latest"] == 5.0  # (+20 and -10) / 2
    assert scores["by_call"][0] == {"call": 1, "avg_score": 50.0, "users": 2}


def test_cost_per_active_user_and_finished_call():
    rows = [{"cost_usd": 0.03}, {"cost_usd": 0.01}]
    assert insights._cost(rows, active=2, finished_calls=4) == {
        "total_usd": 0.04,
        "per_active_user_usd": 0.02,
        "per_finished_call_usd": 0.01,
    }
    assert insights._cost([], 0, 0)["per_active_user_usd"] is None


# ---- alerts ----------------------------------------------------------------------------------


def _day(requests=100, errors=0, replies=10, p95_ms=2000, fallbacks=0, model_calls=20):
    return {
        "requests": requests,
        "errors": errors,
        "error_pct": round(100 * errors / requests, 1) if requests else None,
        "reply": {"count": replies, "p50_ms": 1000, "p95_ms": p95_ms},
        "fallbacks": {
            "model_fallbacks": fallbacks,
            "model_calls": model_calls,
            "model_fallback_pct": round(100 * fallbacks / model_calls, 1) if model_calls else None,
        },
    }


def _evaluate(spend=0.1, chars=0, day=None, last_call_days=0.5):
    last = (NOW - timedelta(days=last_call_days)).isoformat(timespec="seconds")
    return alerts.evaluate(
        spend={"today_usd": spend, "daily_cap_usd": 2.0},
        voice_budget={"chars_this_month": chars, "monthly_cap": 18000},
        day=day or _day(),
        last_call_at=last,
        now=NOW,
    )


def test_healthy_service_raises_no_alerts():
    assert _evaluate() == []


@pytest.mark.parametrize(
    ("kwargs", "alert_id", "level"),
    [
        ({"spend": 1.7}, "spend", "warning"),
        ({"spend": 2.0}, "spend", "critical"),
        ({"chars": 15000}, "voice", "warning"),
        ({"day": _day(fallbacks=5, model_calls=20)}, "fallback", "critical"),
        ({"day": _day(p95_ms=9500)}, "slow_replies", "warning"),
        ({"day": _day(errors=5)}, "errors", "critical"),
        ({"last_call_days": 4}, "quiet", "warning"),
    ],
)
def test_each_alert_fires_with_a_plain_reason(kwargs, alert_id, level):
    firing = _evaluate(**kwargs)
    assert [a["id"] for a in firing] == [alert_id]
    assert firing[0]["level"] == level and firing[0]["reason"]


def test_rates_need_enough_traffic_before_alerting():
    assert _evaluate(day=_day(requests=10, errors=3)) == []
    assert _evaluate(day=_day(fallbacks=2, model_calls=3)) == []
    assert _evaluate(day=_day(replies=2, p95_ms=20000)) == []


def test_critical_alerts_come_first():
    firing = _evaluate(chars=17000, day=_day(errors=10))
    assert [a["id"] for a in firing] == ["errors", "voice"]


# ---- the route -------------------------------------------------------------------------------


def test_insights_are_admin_only(agent1, anon):
    assert agent1.get("/api/admin/insights").status_code == 403
    assert anon.get("/api/admin/insights").status_code == 401


def test_only_7_or_30_days(client):
    assert client.get("/api/admin/insights?days=9").status_code == 422


def test_insights_reflect_a_finished_call_without_emails_or_text(client, agent2):
    before = client.get("/api/admin/insights?days=30").json()
    sid = agent2.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    agent2.post(f"/api/sessions/{sid}/turns", json={"text": "Tell me about your shop, please."})
    agent2.post(f"/api/sessions/{sid}/end")
    res = client.get("/api/admin/insights?days=30")
    assert res.status_code == 200
    after = res.json()
    calls = {f["feature"]: f["uses"] for f in after["business"]["features"]}["Practice calls"]
    calls_before = {f["feature"]: f["uses"] for f in before["business"]["features"]}[
        "Practice calls"
    ]
    assert calls == calls_before + 1
    assert after["engineering"]["reply"]["count"] >= 1
    assert len(after["business"]["daily_active"]) == 30
    body = res.text
    assert "@example.com" not in body and "Tell me about your shop" not in body
    assert sid not in body


def test_admin_activity_is_left_out_of_adoption(client):
    client.get("/api/me")  # the admin is active today
    admin = frozenset({"dev:admin@example.com"})
    with_admin = insights.business(7)["active_users"]
    assert insights.business(7, exclude=admin)["active_users"] == with_admin - 1

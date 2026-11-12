"""Events for Insights: request timings, route templates (no ids or text), fallbacks, retention."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app import events
from app.db import engine

SCENARIO = "price-worried-owner"


def _latest(kind: str, name: str | None = None) -> dict:
    start = datetime.now(UTC) - timedelta(minutes=5)
    rows = [r for r in events.since(start, kind) if name is None or r["name"] == name]
    assert rows, f"no {kind} event {name or ''}"
    return rows[-1]


def test_api_request_is_recorded_with_route_template_status_and_user(agent1):
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hi, how do you keep your books?"})
    row = _latest("request", "POST /api/sessions/{sid}/turns")
    assert row["status"] == 200
    assert row["latency_ms"] is not None and row["latency_ms"] >= 0
    assert row["user_id"] == "dev:agent1@example.com"
    assert sid not in row["name"]


def test_failed_and_anonymous_requests_are_recorded(anon):
    assert anon.get("/api/me").status_code == 401
    row = _latest("request", "GET /api/me")
    assert row["status"] == 401 and row["user_id"] is None


def test_unknown_api_path_does_not_leak_the_path(agent1):
    agent1.get("/api/no-such-thing/secret-looking-id")
    row = _latest("request")
    assert "secret-looking-id" not in row["name"]


def test_pages_and_health_are_not_recorded(anon):
    before = len(events.since(datetime.now(UTC) - timedelta(minutes=5), "request"))
    anon.get("/health")
    anon.get("/")
    after = len(events.since(datetime.now(UTC) - timedelta(minutes=5), "request"))
    assert after == before


def test_model_failure_records_a_fallback_without_text(agent1, fake_llm):
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    fake_llm([RuntimeError("model down: secret words")] * 4)
    res = agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hello there"})
    assert res.json()["fallback"] is True
    row = _latest("fallback", "coach.turn")
    assert row["detail"] in {"RuntimeError", "ModelReplyError"}
    assert "secret" not in (row["detail"] or "")


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        events.record("whatever", "x")


def test_old_events_are_pruned():
    old = (datetime.now(UTC) - timedelta(days=events.RETENTION_DAYS + 1)).isoformat()
    with engine().begin() as conn:
        conn.execute(
            text("INSERT INTO events (created_at, kind, name) VALUES (:t, 'request', 'old')"),
            {"t": old},
        )
    assert events.prune() >= 1
    with engine().connect() as conn:
        left = conn.execute(text("SELECT COUNT(*) FROM events WHERE name = 'old'")).scalar_one()
    assert left == 0


def test_recording_never_raises_when_the_database_fails(monkeypatch):
    def broken():
        raise RuntimeError("db gone")

    monkeypatch.setattr(events, "engine", broken)
    events.record("request", "GET /api/me", status=200)  # logged, not raised

"""Spend guard: token usage and cost per model call, daily caps, per-user rate limit."""

import json
from types import SimpleNamespace

import pytest
from test_model_path import GOOD_TURN, _anthropic_with

from app import limits, llm, store, usage

SCENARIO = "price-worried-owner"
LIMIT_MESSAGE = "limit reached"


@pytest.fixture(autouse=True)
def fresh_limits():
    limits.reset_for_tests()
    usage.reset_for_tests()
    yield
    limits.reset_for_tests()
    usage.reset_for_tests()


def test_cost_comes_from_config_prices():
    cost = usage.cost_usd("claude-haiku-5-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(0.60)
    unknown = usage.cost_usd("some-new-model", input_tokens=1_000_000, output_tokens=0)
    assert unknown == pytest.approx(5.00)  # unknown models are priced high, never free


def test_anthropic_reply_usage_is_recorded_against_the_call():
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="{}")],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    with usage.attribute(session_id="s1", user_id="u1"), usage.kind("turn"):
        _anthropic_with(reply).complete(system="s", user="u", max_tokens=10)
    rows = usage.rows_for_session("s1")
    assert len(rows) == 1
    row = rows[0]
    assert (row["kind"], row["user_id"], row["input_tokens"], row["output_tokens"]) == (
        "turn",
        "u1",
        1000,
        200,
    )
    assert row["cost_usd"] == pytest.approx(1000 * 0.10 / 1e6 + 200 * 0.50 / 1e6)


def test_daily_spend_cap_blocks_new_calls_but_not_the_rest(monkeypatch, client, agent1):
    cap = usage.spend_today() + 0.10
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", str(cap))
    assert agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).status_code == 200
    usage.record("claude-haiku-5-5", 1_000_000, 100_000, kind="turn", session_id="x", user_id="u")
    assert usage.spend_today() >= cap
    res = agent1.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert res.status_code == 429 and LIMIT_MESSAGE in res.json()["detail"].lower()
    assert agent1.get("/api/sessions").status_code == 200  # history still works


def test_calls_per_user_per_day(monkeypatch, agent1, agent2):
    already = usage.calls_today("dev:agent1@example.com")
    monkeypatch.setenv("MAX_CALLS_PER_USER_PER_DAY", str(already + 2))
    for _ in range(2):
        assert agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).status_code == 200
    blocked = agent1.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert blocked.status_code == 429 and LIMIT_MESSAGE in blocked.json()["detail"].lower()
    assert agent2.post("/api/sessions", json={"scenario_id": SCENARIO}).status_code == 200


def test_rate_limit_per_user(monkeypatch, agent1, agent2):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    codes = [agent1.get("/api/me").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert agent2.get("/api/me").status_code == 200  # someone else is not affected


def test_admin_sees_cost_of_a_call_and_agents_do_not(client, agent1, fake_llm):
    fake_llm([GOOD_TURN])
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hi"})
    usage.record("claude-haiku-5-5", 2000, 300, kind="turn", session_id=sid, user_id="u")
    assert client.get(f"/api/sessions/{sid}").json()["cost_usd"] > 0
    assert "cost_usd" not in agent1.get(f"/api/sessions/{sid}").json()
    llm.set_llm_for_tests(None)


def test_usage_rows_survive_in_the_database():
    usage.record("claude-haiku-5-5", 10, 5, kind="survey", session_id="s9", user_id="u9")
    with store._tx() as conn:
        from sqlalchemy import text

        row = conn.execute(text("SELECT kind, model FROM usage WHERE session_id='s9'")).one()
    assert tuple(row) == ("survey", "claude-haiku-5-5")
    assert json.dumps(usage.rows_for_session("s9"))  # serialisable for the API

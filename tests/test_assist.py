"""Live coach assist: the next move for the agent while the customer is still talking.

The hint is written from what the agent may know (the public brief, the conversation, the rubric
and the product facts), never from the customer's hidden objections or private persona."""

import json
from datetime import UTC, datetime, timedelta

from app import coach, events

SCENARIO = "price-worried-owner"
STAGES = {"opening", "discovery", "value", "objection", "close"}


def _start(c) -> str:
    return c.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]


def _move(**over) -> str:
    base = {
        "stage": "discovery",
        "move": "Ask what her month-end looks like today.",
        "avoid": "Quoting the price yet.",
        "line": "Before anything else, how do you keep your books today?",
    }
    return json.dumps({**base, **over})


def test_offline_gives_a_next_move_from_the_first_line(agent1):
    sid = _start(agent1)
    res = agent1.post(f"/api/sessions/{sid}/assist")
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == "opening"
    assert body["move"] and body["line"]
    assert body["fallback"] is False


def test_offline_moves_on_through_the_call(agent1):
    sid = _start(agent1)
    for text in ["Hi Meera, thanks for taking the call.", "How do you do your books today?"]:
        agent1.post(f"/api/sessions/{sid}/turns", json={"text": text})
    assert agent1.post(f"/api/sessions/{sid}/assist").json()["stage"] in STAGES - {"opening"}


def test_the_coach_never_sees_hidden_objections(agent1, fake_llm):
    fake = fake_llm(['{"customer": "Okay, go on.", "done": false, "coach": {}}', _move()])
    sid = _start(agent1)
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Meera, how are the books?"})
    body = agent1.post(f"/api/sessions/{sid}/assist").json()
    assert body["move"] == "Ask what her month-end looks like today."
    assert body["stage"] == "discovery"
    prompt = fake.calls[-1]["system"] + fake.calls[-1]["user"]
    customer = coach.get_scenario(SCENARIO)["customer"]
    for secret in customer["hidden_objections"]:
        assert secret not in prompt
    for private in ("persona", "situation", "wins_if", "walks_away_if"):
        assert customer[private] not in prompt
    assert coach.load_product().strip()[:80] in prompt  # claims are checked against the facts
    assert "Okay, go on." in prompt  # it reacts to what the customer actually said


def test_unknown_stage_from_the_model_is_replaced(agent1, fake_llm):
    fake_llm([_move(stage="banter")])
    sid = _start(agent1)
    assert agent1.post(f"/api/sessions/{sid}/assist").json()["stage"] in STAGES


def test_model_failure_falls_back_to_a_scripted_move(agent1, fake_llm):
    fake_llm([ValueError("bad"), ValueError("bad again")])
    sid = _start(agent1)
    body = agent1.post(f"/api/sessions/{sid}/assist").json()
    assert body["fallback"] is True and body["move"]
    recent = events.since(datetime.now(UTC) - timedelta(minutes=5), "fallback")
    assert any(r["name"] == "coach.assist" for r in recent)


def test_over_the_spend_cap_uses_the_scripted_move(agent1, fake_llm, monkeypatch):
    sid = _start(agent1)
    fake = fake_llm([_move()])
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "0")
    body = agent1.post(f"/api/sessions/{sid}/assist").json()
    assert fake.calls == [] and body["move"]


def test_only_the_calls_owner_gets_a_move(agent1, agent2):
    sid = _start(agent1)
    assert agent2.post(f"/api/sessions/{sid}/assist").status_code == 404


def test_no_move_after_the_call_ends(agent1):
    sid = _start(agent1)
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Meera, how are the books?"})
    agent1.post(f"/api/sessions/{sid}/end")
    assert agent1.post(f"/api/sessions/{sid}/assist").status_code == 409

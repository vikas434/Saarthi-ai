"""Roleplay builder and personas: private by default, published by the admin, goals scored."""

import json

import pytest
from sqlalchemy import text

from app import db, store


def _body(**changes) -> dict:
    body = {
        "title": "Clinic owner who hates software",
        "difficulty": "Hard",
        "public_brief": "Dr Rao runs a small clinic and agreed to a 10-minute call.",
        "customer": {
            "name": "Dr Rao",
            "role": "Clinic owner",
            "persona": "Busy doctor, polite, short on time.",
            "mood": "Skeptical",
            "situation": "Keeps accounts in a paper register.",
            "hidden_objections": ["Worried staff can't learn new software"],
            "wins_if": "The agent asks about the clinic first.",
            "walks_away_if": "The agent talks jargon.",
        },
        "opening_line": "I have ten minutes. Go ahead.",
        "minutes": 5,
        "goals": [
            {"name": "Find the pain", "description": "Ask how accounts are kept", "weight": 2},
            {"name": "Book a demo", "description": "Agree a specific next step", "weight": 1},
        ],
    }
    return {**body, **changes}


def _save(c, **changes) -> dict:
    res = c.post("/api/roleplays", json=_body(**changes))
    assert res.status_code == 200, res.text
    return res.json()


def _visible_ids(c) -> set[str]:
    return {s["id"] for s in c.get("/api/config").json()["scenarios"]}


def test_templates_are_full_roleplays(agent1):
    templates = agent1.get("/api/roleplays/templates").json()
    assert len(templates) >= 5
    for t in templates:
        assert t["title"] and t["customer"]["name"] and t["opening_line"] and t["goals"]


def test_draft_from_a_description_is_complete_and_not_saved(agent1):
    before = _visible_ids(agent1)
    res = agent1.post("/api/roleplays/draft", json={"description": "A gym owner on a budget"})
    assert res.status_code == 200
    draft = res.json()
    assert draft["customer"]["hidden_objections"] and draft["goals"] and draft["minutes"]
    assert _visible_ids(agent1) == before


def test_saved_roleplay_is_private_to_its_builder(agent1, agent2):
    made = _save(agent1)
    rid = made["id"]
    mine = next(s for s in agent1.get("/api/config").json()["scenarios"] if s["id"] == rid)
    assert mine["mine"] is True and mine["published"] is False
    assert "hidden_objections" not in json.dumps(mine) and "paper register" not in json.dumps(mine)
    assert rid not in _visible_ids(agent2)
    assert agent2.get(f"/api/roleplays/{rid}").status_code == 404
    assert agent2.post("/api/sessions", json={"scenario_id": rid}).status_code == 404
    assert agent1.post("/api/sessions", json={"scenario_id": rid}).status_code == 200


def test_builder_sees_and_edits_the_full_roleplay(agent1, agent2):
    rid = _save(agent1)["id"]
    full = agent1.get(f"/api/roleplays/{rid}").json()
    assert full["customer"]["hidden_objections"] == ["Worried staff can't learn new software"]
    changed = agent1.put(f"/api/roleplays/{rid}", json=_body(title="Renamed clinic call"))
    assert changed.status_code == 200 and changed.json()["title"] == "Renamed clinic call"
    assert agent2.put(f"/api/roleplays/{rid}", json=_body()).status_code == 404
    assert agent2.delete(f"/api/roleplays/{rid}").status_code == 404
    assert agent1.delete(f"/api/roleplays/{rid}").status_code == 200
    assert rid not in _visible_ids(agent1)


def test_admin_publishes_to_everyone_but_objections_stay_hidden(client, agent1, agent2):
    rid = _save(agent1)["id"]
    assert agent1.post(f"/api/roleplays/{rid}/publish", json={"published": True}).status_code == 403
    assert client.post(f"/api/roleplays/{rid}/publish", json={"published": True}).status_code == 200
    seen = next(s for s in agent2.get("/api/config").json()["scenarios"] if s["id"] == rid)
    assert seen["published"] is True and seen["mine"] is False
    assert agent2.post("/api/sessions", json={"scenario_id": rid}).status_code == 200
    assert agent2.get(f"/api/roleplays/{rid}").status_code == 404
    client.post(f"/api/roleplays/{rid}/publish", json={"published": False})
    assert rid not in _visible_ids(agent2)


@pytest.mark.parametrize(
    "bad",
    [
        {"title": ""},
        {"minutes": 30},
        {"opening_line": ""},
        {"goals": [{"name": "g", "description": "", "weight": 1}] * 7},
    ],
)
def test_roleplay_validation(agent1, bad):
    assert agent1.post("/api/roleplays", json=_body(**bad)).status_code == 422


def test_too_many_hidden_objections_is_refused(agent1):
    customer = {**_body()["customer"], "hidden_objections": ["x"] * 16}
    assert agent1.post("/api/roleplays", json=_body(customer=customer)).status_code == 422


def test_roleplays_per_person_are_capped(monkeypatch, agent2):
    have = len([s for s in agent2.get("/api/config").json()["scenarios"] if s["mine"]])
    monkeypatch.setenv("MAX_ROLEPLAYS_PER_USER", str(have + 1))
    _save(agent2)
    blocked = agent2.post("/api/roleplays", json=_body())
    assert blocked.status_code == 429 and "roleplays" in blocked.json()["detail"]


def test_draft_stops_when_the_daily_spend_cap_is_reached(monkeypatch, agent1):
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "0")
    res = agent1.post("/api/roleplays/draft", json={"description": "A gym owner"})
    assert res.status_code == 429


def test_goals_are_scored_on_the_scorecard(agent1):
    rid = _save(agent1)["id"]
    sid = agent1.post("/api/sessions", json={"scenario_id": rid}).json()["id"]
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "How do you keep accounts today?"})
    report = agent1.post(f"/api/sessions/{sid}/end").json()["report"]
    goals = next(m for m in report["markers"] if m["id"] == "goals")
    assert goals["type"] == "rubric"
    assert [b["name"] for b in goals["behaviors"]] == ["Find the pain", "Book a demo"]
    assert [b["weight"] for b in goals["behaviors"]] == [2, 1]


def test_personas_library_and_private_personas(agent1, agent2):
    library = agent1.get("/api/personas").json()
    assert len([p for p in library if p["built_in"]]) >= 5
    made = agent1.post(
        "/api/personas",
        json={"name": "Kavya", "role": "CFO", "mood": "Blunt", "background": "Hates waste."},
    ).json()
    assert any(p["id"] == made["id"] for p in agent1.get("/api/personas").json())
    assert all(p["id"] != made["id"] for p in agent2.get("/api/personas").json())
    assert agent2.delete(f"/api/personas/{made['id']}").status_code == 404
    assert agent1.delete(f"/api/personas/{made['id']}").status_code == 200


def test_built_in_and_older_custom_scenarios_stay_visible(agent2):
    store.save_scenario({"id": "custom-legacy", **_body(title="Legacy one")})
    ids = _visible_ids(agent2)
    assert "price-worried-owner" in ids and "custom-legacy" in ids
    with db.engine().begin() as conn:
        conn.execute(text("DELETE FROM scenarios WHERE id = 'custom-legacy'"))

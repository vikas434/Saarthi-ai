"""Hands-free voice calls: speaking time per reply, a time limit per roleplay, a reply cap."""

from app import coach

SCENARIO = "price-worried-owner"


def _start(c) -> str:
    res = c.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_spoken_reply_keeps_its_speaking_time(client):
    sid = _start(client)
    res = client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Maria", "seconds": 3.4})
    assert res.status_code == 200
    turns = client.get(f"/api/sessions/{sid}").json()["turns"]
    assert turns[-1]["agent_seconds"] == 3.4


def test_typed_reply_has_no_speaking_time(client):
    sid = _start(client)
    client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Maria"})
    assert client.get(f"/api/sessions/{sid}").json()["turns"][-1]["agent_seconds"] is None


def test_speaking_time_must_be_sensible(client):
    sid = _start(client)
    for bad in (-1, 601):
        res = client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi", "seconds": bad})
        assert res.status_code == 422


def test_every_roleplay_has_a_time_limit_and_no_hidden_objections(client):
    scenarios = client.get("/api/config").json()["scenarios"]
    assert all(s["minutes"] == coach.DEFAULT_CALL_MINUTES for s in scenarios)
    assert "hidden_objections" not in str(scenarios)
    started = client.post("/api/sessions", json={"scenario_id": SCENARIO}).json()
    assert started["scenario"]["minutes"] == coach.DEFAULT_CALL_MINUTES


def test_a_roleplay_can_set_its_own_time_limit():
    scenario = {**coach.get_scenario(SCENARIO), "minutes": 3}
    assert coach.public_scenario(scenario)["minutes"] == 3


def test_reply_cap_stops_long_calls(monkeypatch, client):
    monkeypatch.setenv("MAX_REPLIES_PER_CALL", "2")
    sid = _start(client)
    for text in ("Hi Maria", "How do you keep your books?"):
        assert client.post(f"/api/sessions/{sid}/turns", json={"text": text}).status_code == 200
    blocked = client.post(f"/api/sessions/{sid}/turns", json={"text": "One more thing"})
    assert blocked.status_code == 409 and "reply limit" in blocked.json()["detail"]
    assert client.post(f"/api/sessions/{sid}/end").status_code == 200


def test_voice_script_is_served_without_sign_in(anon):
    res = anon.get("/voice.js")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/javascript")
    assert "SaarthiVoice" in res.text


def test_report_script_is_served_and_other_names_are_not(anon):
    assert "showReport" in anon.get("/report.js").text
    assert anon.get("/secrets.js").status_code == 404

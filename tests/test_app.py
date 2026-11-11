import json

from app import coach
from app.evals import run

SCENARIO = "price-worried-owner"


def start(client):
    res = client.post("/api/sessions", json={"scenario_id": SCENARIO, "agent_name": "Asha"})
    assert res.status_code == 200, res.text
    return res.json()


def test_config_hides_the_customers_hidden_objections(client):
    cfg = client.get("/api/config").json()
    assert cfg["mode"] == "offline"
    assert len(cfg["scenarios"]) >= 3
    assert "hidden_objections" not in json.dumps(cfg["scenarios"])
    assert "burned" not in json.dumps(cfg["scenarios"])


def test_offline_call_end_to_end(client):
    s = start(client)
    assert "Meera" in s["customer"]
    r = client.post(
        f"/api/sessions/{s['id']}/turns",
        json={"text": "Hi Meera, how do you keep your books today?"},
    )
    body = r.json()
    assert body["customer"] and body["coach"]["verdict"] == "good"
    assert body["coach"]["behavior"] == "discovery"
    ended = client.post(f"/api/sessions/{s['id']}/end").json()
    assert 0 <= ended["report"]["sqs"] <= 100
    assert len(ended["report"]["behaviors"]) == len(coach.load_rubric()["behaviors"])
    # ending twice returns the same report, and no more turns are accepted
    assert client.post(f"/api/sessions/{s['id']}/end").json()["report"] == ended["report"]
    assert client.post(f"/api/sessions/{s['id']}/turns", json={"text": "hello"}).status_code == 409
    assert client.get("/api/sessions").json()[0]["scenario_title"]
    assert client.get("/api/progress").json()["sessions"] >= 1


def test_cannot_score_an_empty_call_or_unknown_ids(client):
    s = start(client)
    assert client.post(f"/api/sessions/{s['id']}/end").status_code == 400
    assert client.post("/api/sessions", json={"scenario_id": "nope"}).status_code == 404
    assert client.get("/api/sessions/nope").status_code == 404


def test_model_turn_gets_persona_product_and_rubric(client, fake_llm):
    fake = fake_llm(
        [
            json.dumps(
                {
                    "customer": "Well, I use Excel.",
                    "done": False,
                    "coach": {
                        "verdict": "good",
                        "behavior": "discovery",
                        "note": "Asked first.",
                        "try_instead": "",
                    },
                }
            )
        ]
    )
    s = start(client)
    r = client.post(
        f"/api/sessions/{s['id']}/turns", json={"text": "How do you keep books?"}
    ).json()
    assert r["customer"] == "Well, I use Excel."
    system = fake.calls[0]["system"]
    assert "Meera" in system and "Rs 999" in system and "discovery" in system
    assert "could not cancel" in system  # hidden objection reaches the model, not the agent
    assert "How do you keep books?" in fake.calls[0]["user"]


def test_bad_model_output_falls_back_and_is_cleaned(client, fake_llm):
    fake_llm(
        [
            "not json at all",
            json.dumps(
                {
                    "customer": "Hmm.",
                    "done": False,
                    "coach": {"verdict": "terrible", "behavior": "made_up", "note": "x"},
                }
            ),
        ]
    )
    s = start(client)
    first = client.post(
        f"/api/sessions/{s['id']}/turns", json={"text": "Buy it today only!"}
    ).json()
    assert first["customer"]  # offline fallback answered
    second = client.post(f"/api/sessions/{s['id']}/turns", json={"text": "ok"}).json()
    assert second["coach"]["verdict"] == "mixed" and second["coach"]["behavior"] == "clarity"


def test_report_is_weighted_and_skips_unscored_behaviours(client, fake_llm):
    rubric = coach.load_rubric()
    behaviors = [
        {"id": b["id"], "score": 5, "evidence": "e", "good": "g", "improve": "", "say_instead": ""}
        for b in rubric["behaviors"]
    ]
    behaviors[0]["score"] = None
    behaviors[1]["score"] = 1
    fake_llm(
        [
            json.dumps(
                {
                    "customer": "ok",
                    "done": True,
                    "coach": {"verdict": "good", "behavior": "empathy", "note": "n"},
                }
            ),
            json.dumps(
                {
                    "behaviors": behaviors,
                    "strengths": ["a"],
                    "growth": ["b"],
                    "summary": "s",
                    "next_drill": "d",
                }
            ),
        ]
    )
    s = start(client)
    client.post(f"/api/sessions/{s['id']}/turns", json={"text": "I understand."})
    report = client.post(f"/api/sessions/{s['id']}/end").json()["report"]
    weights = {b["id"]: b["weight"] for b in rubric["behaviors"]}
    scored = [(weights[b["id"]], b["score"]) for b in behaviors if b["score"]]
    expected = round(100 * sum(w * x for w, x in scored) / (5 * sum(w for w, _ in scored)), 1)
    assert report["sqs"] == expected
    assert report["behaviors"][0]["score"] is None
    assert report["scored_by"] == "fake"


def test_product_and_scenario_setup(client):
    text = "Acme CRM. Rs 500 per user per month. 14-day trial. No refunds."
    assert client.put("/api/product", json={"text": text}).status_code == 200
    assert client.get("/api/config").json()["product"] == text
    made = client.post("/api/scenarios", json={"description": "A doctor who hates software"}).json()
    assert made["id"].startswith("custom-")
    assert any(s["id"] == made["id"] for s in client.get("/api/config").json()["scenarios"])
    assert client.post("/api/sessions", json={"scenario_id": made["id"]}).status_code == 200


def test_eval_strong_agent_beats_weak_agent_offline(client):
    strong, weak = run()
    assert strong["sqs"] - weak["sqs"] >= 15

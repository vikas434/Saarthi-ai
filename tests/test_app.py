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
    report = ended["report"]
    assert 0 <= report["sqs"] <= 100
    by_id = {m["id"]: m for m in report["markers"]}
    assert set(by_id) >= {"sqs", "tnps", "prosat", "call-checklist"}
    assert len(by_id["sqs"]["behaviors"]) == len(coach.load_rubric()["behaviors"])
    assert 0 <= by_id["tnps"]["score"] <= 10 and 1 <= by_id["prosat"]["score"] <= 5
    assert by_id["tnps"]["drivers"] and by_id["call-checklist"]["applicable"] >= 1
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


def test_report_scores_every_marker_type(client, fake_llm):
    markers = coach.load_markers()
    sqs = next(m for m in markers if m["id"] == "sqs")
    behaviors = [
        {"id": b["id"], "score": 5, "evidence": "e", "good": "g"} for b in sqs["behaviors"]
    ]
    behaviors[0]["score"] = None
    behaviors[1]["score"] = 1
    coach_reply = json.dumps(
        {
            "behaviors": behaviors,
            "checklist": [
                {"id": "call-checklist.greeting", "result": "yes", "evidence": "Hi Meera"},
                {"id": "call-checklist.needs", "result": "no", "evidence": "pitched first"},
                {"id": "call-checklist.next-step", "result": "weird"},
            ],
            "strengths": ["a"],
            "growth": ["b"],
            "summary": "s",
            "next_drill": "d",
        }
    )
    survey_reply = json.dumps(
        {
            "answers": [
                {"id": "tnps", "score": 14, "reason": "He listened."},
                {"id": "prosat", "score": 4, "reason": "Seems to fit."},
            ]
        }
    )

    class ByPrompt:
        name = "fake"

        def complete(self, *, system, user, max_tokens):
            if "The call is over" in system:
                assert "Meera" in system and "0 to 10" in system
                return survey_reply
            if "sales coach scoring" in system:
                assert "call-checklist.needs" in system
                return coach_reply
            return json.dumps(
                {
                    "customer": "ok",
                    "done": True,
                    "coach": {"verdict": "good", "behavior": "empathy", "note": "n"},
                }
            )

    from app import llm

    llm.set_llm_for_tests(ByPrompt())
    s = start(client)
    client.post(f"/api/sessions/{s['id']}/turns", json={"text": "I understand."})
    report = client.post(f"/api/sessions/{s['id']}/end").json()["report"]
    by_id = {m["id"]: m for m in report["markers"]}
    weights = {b["id"]: b["weight"] for b in sqs["behaviors"]}
    scored = [(weights[b["id"]], b["score"]) for b in behaviors if b["score"]]
    expected = round(100 * sum(w * x for w, x in scored) / (5 * sum(w for w, _ in scored)), 1)
    assert report["sqs"] == by_id["sqs"]["percent"] == expected
    assert by_id["sqs"]["behaviors"][0]["score"] is None
    assert by_id["tnps"]["score"] == 10  # clamped to the scale
    assert by_id["tnps"]["reason"] == "He listened." and by_id["prosat"]["score"] == 4
    checklist = by_id["call-checklist"]
    assert (checklist["passed"], checklist["applicable"]) == (1, 2)
    assert checklist["critical_missed"] == [
        "Asked at least one question about the customer's needs before pitching"
    ]
    assert next(i for i in checklist["items"] if i["id"] == "next-step")["result"] == "na"


def test_custom_markers_are_scored_on_the_next_call(client):
    made = client.post(
        "/api/markers",
        json={
            "name": "Compliance",
            "type": "checklist",
            "lines": ["!Greeted the customer by name", "Offered a next step"],
        },
    ).json()
    assert made["id"] == "custom-compliance" and made["items"][0]["critical"] is True
    rubric = client.post(
        "/api/markers",
        json={
            "name": "Tone",
            "type": "rubric",
            "lines": ["Warmth - Sounds friendly and patient"],
        },
    ).json()
    survey = client.post(
        "/api/markers",
        json={
            "name": "Effort",
            "type": "survey",
            "question": "How easy was it?",
            "min": 1,
            "max": 7,
        },
    ).json()
    assert client.post("/api/markers", json={"name": "Bad", "type": "checklist"}).status_code == 422
    assert client.post("/api/markers", json={"name": "Bad", "type": "other"}).status_code == 422

    s = start(client)
    client.post(
        f"/api/sessions/{s['id']}/turns", json={"text": "Hi Meera, how are the books going?"}
    )
    report = client.post(f"/api/sessions/{s['id']}/end").json()["report"]
    by_id = {m["id"]: m for m in report["markers"]}
    assert by_id[made["id"]]["type"] == "checklist" and by_id[made["id"]]["applicable"] >= 1
    assert by_id[rubric["id"]]["behaviors"][0]["name"] == "Warmth"
    assert by_id[survey["id"]]["max"] == 7 and 1 <= by_id[survey["id"]]["score"] <= 7
    ids = [m["id"] for m in client.get("/api/progress").json()["markers"]]
    assert made["id"] in ids

    for m in (made, rubric, survey):
        assert client.delete(f"/api/markers/{m['id']}").status_code == 200
    assert client.delete("/api/markers/sqs").status_code == 404


def test_product_and_scenario_setup(client):
    text = "Acme CRM. Rs 500 per user per month. 14-day trial. No refunds."
    assert client.put("/api/product", json={"text": text}).status_code == 200
    assert client.get("/api/config").json()["product"] == text
    made = client.post("/api/scenarios", json={"description": "A doctor who hates software"}).json()
    assert made["id"].startswith("custom-")
    assert any(s["id"] == made["id"] for s in client.get("/api/config").json()["scenarios"])
    assert client.post("/api/sessions", json={"scenario_id": made["id"]}).status_code == 200


def test_eval_strong_agent_beats_weak_agent_offline(client):
    from app.evals import marker

    strong, weak = run()
    assert strong["sqs"] - weak["sqs"] >= 15
    assert marker(strong, "tnps")["score"] > marker(weak, "tnps")["score"]
    assert marker(weak, "call-checklist")["critical_missed"]
    assert not marker(strong, "call-checklist")["critical_missed"]

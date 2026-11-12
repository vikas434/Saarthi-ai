"""Tutor mode: learn the product facts, answer three check questions, then practise."""

import json

from app import llm, usage

SCENARIO = "price-worried-owner"
HIDDEN = "burned by a software subscription"


def _start(c, scenario=SCENARIO):
    res = c.post("/api/tutor", json={"scenario_id": scenario})
    assert res.status_code == 200, res.text
    return res.json()


def test_lesson_teaches_facts_and_hides_answers_and_objections(agent1):
    lesson = _start(agent1)
    assert len(lesson["points"]) >= 3 and all(p["title"] and p["explain"] for p in lesson["points"])
    assert len(lesson["questions"]) == 3 and all(isinstance(q, str) for q in lesson["questions"])
    text = json.dumps(lesson).lower()
    assert '"answer":' not in text and HIDDEN not in text


def test_right_and_wrong_answers_offline(agent1):
    # Offline lessons are the same each time, so a second lesson asks the same questions.
    first_sid = _start(agent1)["id"]
    wrong = agent1.post(f"/api/tutor/{first_sid}/answers", json={"index": 0, "text": "no idea"})
    wrong = wrong.json()
    assert wrong["correct"] is False and wrong["ideal"] and wrong["feedback"]
    second_sid = _start(agent1)["id"]
    right = agent1.post(
        f"/api/tutor/{second_sid}/answers", json={"index": 0, "text": wrong["ideal"]}
    )
    assert right.json()["correct"] is True


def test_each_question_is_answered_once(agent1):
    sid = _start(agent1)["id"]
    assert (
        agent1.post(f"/api/tutor/{sid}/answers", json={"index": 0, "text": "a"}).status_code == 200
    )
    again = agent1.post(f"/api/tutor/{sid}/answers", json={"index": 0, "text": "b"})
    assert again.status_code == 409
    assert (
        agent1.post(f"/api/tutor/{sid}/answers", json={"index": 3, "text": "c"}).status_code == 422
    )


def test_only_the_learner_can_answer(agent1, agent2):
    sid = _start(agent1)["id"]
    assert (
        agent2.post(f"/api/tutor/{sid}/answers", json={"index": 0, "text": "a"}).status_code == 404
    )
    assert agent2.post(f"/api/tutor/{sid}/end").status_code == 404


def test_finish_gives_a_score_and_stays_out_of_roleplay_progress(agent1):
    before = agent1.get("/api/progress").json()["sessions"]
    lesson = _start(agent1)
    sid = lesson["id"]
    ideal = agent1.post(f"/api/tutor/{sid}/answers", json={"index": 0, "text": "x"}).json()["ideal"]
    result = agent1.post(f"/api/tutor/{sid}/end").json()
    assert result["score"] == 0 and result["total"] == 3 and result["ready"] is False
    assert ideal and result["message"]
    assert agent1.get("/api/progress").json()["sessions"] == before
    row = next(s for s in agent1.get("/api/sessions").json() if s["id"] == sid)
    assert row["kind"] == "tutor" and row["tutor_score"] == "0 / 3"
    assert agent1.post(f"/api/sessions/{sid}/turns", json={"text": "hi"}).status_code == 409
    assert agent1.post(f"/api/sessions/{sid}/end").status_code == 409


def test_tutor_counts_as_a_call_toward_the_daily_limit(monkeypatch, agent2):
    usage.reset_for_tests()
    already = usage.calls_today("dev:agent2@example.com")
    monkeypatch.setenv("MAX_CALLS_PER_USER_PER_DAY", str(already + 1))
    _start(agent2)
    blocked = agent2.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert blocked.status_code == 429
    assert agent2.post("/api/tutor", json={"scenario_id": SCENARIO}).status_code == 429


def test_tutor_needs_a_roleplay_you_can_see(agent1):
    assert agent1.post("/api/tutor", json={"scenario_id": "nope"}).status_code == 404


def test_model_tutor_uses_product_facts_only(agent1):
    seen = {}

    class Tutor:
        name = "fake"

        def complete(self, *, system, user, max_tokens, schema=None, effort=None):
            if "You are a product tutor" in system:
                seen["lesson"] = system + user
                assert schema and "questions" in schema["properties"]
                return json.dumps(
                    {
                        "intro": "Let's get the facts straight.",
                        "points": [
                            {"title": "Price", "explain": "Starter is Rs 999 a month."},
                            {"title": "Trial", "explain": "30 days free, no card."},
                            {"title": "Cancel", "explain": "Cancel any time."},
                        ],
                        "questions": [
                            {"question": "What does Starter cost?", "answer": "Rs 999 a month"},
                            {"question": "How long is the trial?", "answer": "30 days"},
                            {"question": "Can she cancel?", "answer": "Any time"},
                        ],
                    }
                )
            seen["grade"] = system + user
            return json.dumps({"correct": True, "feedback": "Right.", "ideal": "Rs 999 a month."})

    llm.set_llm_for_tests(Tutor())
    lesson = _start(agent1)
    assert lesson["questions"][0] == "What does Starter cost?"
    from app import coach

    assert coach.load_product()[-60:] in seen["lesson"] and HIDDEN not in seen["lesson"]
    reply = agent1.post(f"/api/tutor/{lesson['id']}/answers", json={"index": 0, "text": "999"})
    assert reply.json() == {"correct": True, "feedback": "Right.", "ideal": "Rs 999 a month."}
    assert "Rs 999 a month" in seen["grade"]  # graded against the hidden answer key


def test_offline_lesson_works_with_plain_text_facts():
    from app import coach, tutor

    plain = "Acme CRM. Rs 500 per user per month. 14-day trial. No refunds after payment."
    lesson = tutor.offline_lesson(coach.get_scenario(SCENARIO), plain)
    assert len(lesson["points"]) >= 3 and len(lesson["questions"]) == 3
    assert any("Rs 500" in q["answer"] for q in lesson["questions"])

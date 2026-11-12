"""Richer report: delivery analytics, overall score, follow-up questions, line-by-line tips."""

import json

from app import delivery, llm

SCENARIO = "price-worried-owner"


def _turn(agent: str | None, customer: str, seconds: float | None = None) -> dict:
    return {"agent_text": agent, "customer_text": customer, "agent_seconds": seconds}


def _metric(result: dict, metric_id: str) -> dict:
    return next(m for m in result["metrics"] if m["id"] == metric_id)


def test_filler_and_weak_words_are_counted():
    turns = [
        _turn(None, "Hello?"),
        _turn("Um, I think we can maybe help, you know.", "Okay."),
        _turn("Basically it just works, uh, I guess.", "Right."),
    ]
    result = delivery.analyze(turns)
    fillers = _metric(result, "filler_words")
    assert fillers["count"] == 4  # um, you know, basically, uh
    assert set(fillers["top"]) >= {"um", "uh"}
    weak = _metric(result, "weak_words")
    assert weak["count"] == 4  # i think, maybe, just, i guess


def test_would_you_like_is_not_a_filler():
    result = delivery.analyze([_turn("Would you like a demo? I like it.", "Sure.")])
    assert _metric(result, "filler_words")["count"] == 0


def test_questions_counted_with_or_without_punctuation():
    turns = [
        _turn("How do you keep your books today? And who does the entries?", "Excel."),
        _turn("what would make sundays easier", "Less typing."),
        _turn("Great, let me show you.", "Okay."),
    ]
    assert _metric(delivery.analyze(turns), "questions")["count"] == 3


def test_talk_time_and_longest_monologue():
    turns = [
        _turn("one two three four five six", "a b"),
        _turn("one two", "a b c d e f g h"),
    ]
    result = delivery.analyze(turns)
    talk = _metric(result, "talk_time")
    assert talk["you_percent"] == 44  # 8 of 18 words
    assert _metric(result, "monologue")["words"] == 6


def test_pace_needs_spoken_replies():
    typed = delivery.analyze([_turn("one two three", "ok")])
    assert typed["spoken"] is False
    assert all(m["id"] != "pace" for m in typed["metrics"])
    words = " ".join(["word"] * 30)
    spoken = delivery.analyze([_turn(words, "ok", 12.0)])
    pace = _metric(spoken, "pace")
    assert spoken["spoken"] is True and pace["wpm"] == 150 and pace["band"] == "conversational"


def test_repeated_sentence_starters_are_flagged():
    text = "I can help. I will check. I think so. Sure thing."
    starters = _metric(delivery.analyze([_turn(text, "ok")]), "sentence_starters")
    assert starters["word"] == "i" and starters["percent"] == 75 and starters["verdict"] == "watch"


def test_analytics_on_an_empty_call_do_not_crash():
    result = delivery.analyze([_turn(None, "Hello?")])
    assert result["metrics"] and result["spoken"] is False


def _call(client) -> str:
    sid = client.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    client.post(
        f"/api/sessions/{sid}/turns",
        json={"text": "Hi Meera, um, how do you keep your books?", "seconds": 4.0},
    )
    client.post(f"/api/sessions/{sid}/turns", json={"text": "It's cheap, just sign up today."})
    return sid


def test_offline_report_has_overall_score_follow_ups_and_analytics(client):
    sid = _call(client)
    report = client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert 0 <= report["overall"] <= 100
    assert report["follow_up_questions"] and all(
        isinstance(q, str) for q in report["follow_up_questions"]
    )
    assert isinstance(report["lines"], list)
    ids = {m["id"] for m in report["analytics"]["metrics"]}
    assert {"filler_words", "questions", "talk_time", "pace"} <= ids


def test_model_line_tips_attach_to_the_right_reply(client):
    class Coach:
        name = "fake"

        def complete(self, *, system, user, max_tokens, schema=None, effort=None):
            if "The call is over" in system:
                return json.dumps({"answers": []})
            if "sales coach scoring" in system:
                props = schema["properties"]
                assert "follow_up_questions" in props and "line_tips" in props
                return json.dumps(
                    {
                        "behaviors": [],
                        "checklist": [],
                        "follow_up_questions": ["How long does moving from Excel take?"],
                        "line_tips": [
                            {"reply": 2, "better": "What would make Sundays easier for you?"},
                            {"reply": 9, "better": "out of range, dropped"},
                        ],
                    }
                )
            return json.dumps(
                {
                    "customer": "Mostly Excel.",
                    "done": False,
                    "coach": {"verdict": "good", "behavior": "discovery", "note": "n"},
                }
            )

    llm.set_llm_for_tests(Coach())
    sid = _call(client)
    report = client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert report["follow_up_questions"] == ["How long does moving from Excel take?"]
    assert report["lines"] == [
        {
            "reply": 2,
            "said": "It's cheap, just sign up today.",
            "better": "What would make Sundays easier for you?",
        }
    ]


def test_overall_blends_every_marker(client):
    from app.coach import overall_score

    markers = [
        {"type": "rubric", "percent": 60.0},
        {"type": "survey", "score": 6, "min": 0, "max": 10},
        {"type": "checklist", "percent": 50.0},
        {"type": "survey", "score": None, "min": 1, "max": 5},
    ]
    assert overall_score(markers) == 57  # (60 + 60 + 50) / 3
    assert overall_score([]) is None

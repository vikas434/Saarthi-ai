"""The real-model path: schemas, one retry on bad JSON, visible fallback, cut-off replies."""

import json
from types import SimpleNamespace

import pytest

from app import llm

SCENARIO = "price-worried-owner"
GOOD_TURN = json.dumps(
    {
        "customer": "Mostly Excel.",
        "done": False,
        "coach": {"verdict": "good", "behavior": "discovery", "note": "n", "try_instead": ""},
    }
)


def _start(client) -> str:
    return client.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]


def test_turn_retries_once_on_bad_json_then_uses_the_model(client, fake_llm):
    fake = fake_llm(["{broken", GOOD_TURN])
    sid = _start(client)
    body = client.post(f"/api/sessions/{sid}/turns", json={"text": "How do you keep books?"}).json()
    assert body["customer"] == "Mostly Excel."
    assert body["fallback"] is False and body["coach"]["fallback"] is False
    assert len(fake.calls) == 2


def test_turn_sends_a_json_schema(client, fake_llm):
    fake = fake_llm([GOOD_TURN])
    sid = _start(client)
    client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi"})
    schema = fake.calls[0]["schema"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == {"customer", "done", "coach"}
    behaviors = schema["properties"]["coach"]["properties"]["behavior"]["enum"]
    assert "discovery" in behaviors and "accuracy" in behaviors


def test_report_falls_back_after_two_bad_replies_and_says_so(client, fake_llm):
    survey = json.dumps({"answers": [{"id": "tnps", "score": 7, "reason": "ok"}]})

    class ByPrompt:
        name = "fake"

        def complete(self, *, system, user, max_tokens, schema=None, effort=None):
            if "The call is over" in system:
                return survey
            if "sales coach scoring" in system:
                return "not json"
            return GOOD_TURN

    llm.set_llm_for_tests(ByPrompt())
    sid = _start(client)
    client.post(f"/api/sessions/{sid}/turns", json={"text": "How do you keep books?"})
    report = client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert report["scored_by"] == "offline" and report["fallback"] is True
    tnps = next(m for m in report["markers"] if m["id"] == "tnps")
    assert tnps["answered_by"] == "fake" and tnps["score"] == 7


def test_report_from_the_model_is_not_a_fallback(client, fake_llm):
    class Empty:
        name = "fake"

        def complete(self, *, system, user, max_tokens, schema=None, effort=None):
            if "The call is over" in system:
                return json.dumps({"answers": []})
            if "sales coach scoring" in system:
                assert schema and "behaviors" in schema["properties"]
                return json.dumps({"behaviors": [], "checklist": []})
            return GOOD_TURN

    llm.set_llm_for_tests(Empty())
    sid = _start(client)
    client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi"})
    report = client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert report["fallback"] is False and report["scored_by"] == "fake"


def _anthropic_with(reply) -> llm.AnthropicLLM:
    model = llm.AnthropicLLM("test-key", "claude-haiku-5-5")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return reply

    model._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    model.sent = sent
    return model


def test_anthropic_call_uses_structured_output_and_low_effort():
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text='{"a": 1}')],
    )
    model = _anthropic_with(reply)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    assert model.complete(system="s", user="u", max_tokens=100, schema=schema) == '{"a": 1}'
    assert model.sent["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert model.sent["output_config"]["effort"] == "low"


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_anthropic_cut_off_or_refused_reply_raises(stop):
    reply = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text="{")])
    with pytest.raises(llm.ModelReplyError):
        _anthropic_with(reply).complete(system="s", user="u", max_tokens=10)


def test_scorecard_is_judged_at_higher_effort_with_an_accuracy_anchor(client):
    seen = {}

    class Record:
        name = "fake"

        def complete(self, *, system, user, max_tokens, schema=None, effort=None):
            if "sales coach scoring" in system:
                seen["report"] = (effort, system)
                return json.dumps({"behaviors": [], "checklist": []})
            if "The call is over" in system:
                return json.dumps({"answers": []})
            seen["turn"] = effort
            return GOOD_TURN

    llm.set_llm_for_tests(Record())
    sid = _start(client)
    client.post(f"/api/sessions/{sid}/turns", json={"text": "Hi"})
    client.post(f"/api/sessions/{sid}/end")
    report_effort, report_system = seen["report"]
    assert report_effort == "medium" and seen["turn"] in (None, "low")
    assert "score accuracy 1" in report_system


def test_anthropic_effort_can_be_raised_per_call():
    reply = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{}")]
    )
    model = _anthropic_with(reply)
    model.complete(system="s", user="u", max_tokens=10, effort="medium")
    assert model.sent["output_config"]["effort"] == "medium"

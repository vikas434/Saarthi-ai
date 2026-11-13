"""The video customer (Anam): a short-lived token per call, Saarthi decides every line, a monthly
minute cap, and voice-only calls whenever video isn't available."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import avatar, events, usage

SCENARIO = "price-worried-owner"


class FakeAnam:
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json})
        body = {"sessionToken": "anam-session-token-for-test"} if self.status == 200 else {}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def anam(monkeypatch):
    fake = FakeAnam()
    monkeypatch.setenv("ANAM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANAM_MONTHLY_MINUTE_CAP", "100000")
    monkeypatch.setattr(avatar.httpx, "post", fake.post)
    avatar.reset_for_tests()
    usage.reset_for_tests()
    yield fake
    avatar.reset_for_tests()


def _start(c) -> str:
    return c.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]


def test_without_a_key_calls_have_no_video(agent1):
    assert agent1.get("/api/config").json()["avatar"] is None
    sid = _start(agent1)
    assert agent1.post(f"/api/sessions/{sid}/avatar").status_code == 204
    csp = agent1.get("/").headers["content-security-policy"]
    assert "anam.ai" not in csp and "esm.sh" not in csp


def test_token_switches_off_anams_llm_and_keeps_the_key_on_the_server(anam, agent1):
    assert agent1.get("/api/config").json()["avatar"] == {"sdk": avatar.SDK_VERSION}
    sid = _start(agent1)
    res = agent1.post(f"/api/sessions/{sid}/avatar")
    assert res.status_code == 200
    assert res.json() == {"session_token": "anam-session-token-for-test"}
    assert "test-key-not-real" not in res.text
    sent = anam.calls[0]
    assert sent["url"] == avatar.TOKEN_URL
    assert sent["headers"]["Authorization"] == "Bearer test-key-not-real"
    persona = sent["json"]["personaConfig"]
    assert persona["llmId"] == "CUSTOMER_CLIENT_V1"
    assert persona["skipGreeting"] is True
    assert persona["name"] == "Meera"
    assert "systemPrompt" not in persona  # no persona, objections or product facts go to Anam
    assert sent["json"]["maxSessions"] == 1


def test_same_customer_same_face(anam):
    meera = {"name": "Meera", "voice": "female"}
    assert avatar.pick(meera) == avatar.pick(dict(meera))
    assert avatar.pick({"name": "Rahul", "voice": "male"})["avatar_id"]  # empty pool falls back


def test_only_the_calls_owner_gets_a_token(anam, agent1, agent2):
    sid = _start(agent1)
    assert agent2.post(f"/api/sessions/{sid}/avatar").status_code == 404


def test_no_token_after_the_call_ends(anam, agent1):
    sid = _start(agent1)
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Meera, how are the books?"})
    agent1.post(f"/api/sessions/{sid}/end")
    assert agent1.post(f"/api/sessions/{sid}/avatar").status_code == 409


def test_planned_minutes_count_against_the_monthly_cap(anam, agent1, monkeypatch):
    before = avatar.seconds_this_month()
    sid = _start(agent1)
    agent1.post(f"/api/sessions/{sid}/avatar")
    assert avatar.seconds_this_month() > before
    monkeypatch.setenv("ANAM_MONTHLY_MINUTE_CAP", str(avatar.seconds_this_month() // 60))
    assert agent1.get("/api/config").json()["avatar"] is None
    assert agent1.post(f"/api/sessions/{_start(agent1)}/avatar").status_code == 204


def test_anam_refusal_falls_back_to_voice_and_is_recorded(anam, agent1):
    anam.status = 402
    sid = _start(agent1)
    assert agent1.post(f"/api/sessions/{sid}/avatar").status_code == 204
    recent = events.since(datetime.now(UTC) - timedelta(minutes=5), "fallback")
    assert any(r["name"] == "avatar.anam" and r["detail"] == "status 402" for r in recent)


def test_csp_allows_anam_only_when_configured(anam, agent1):
    csp = agent1.get("/").headers["content-security-policy"]
    assert "https://esm.sh" in csp and "wss://connect.anam.ai" in csp
    assert "mediastream:" in csp

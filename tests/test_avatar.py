"""The video customer (Anam): a short-lived token per call, Saarthi decides every line, a monthly
minute cap, and voice-only calls whenever video isn't available."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import avatar, events, usage

SCENARIO = "price-worried-owner"


def _session(start: datetime, seconds: int) -> dict:
    return {
        "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "sessionLengthMs": seconds * 1000,
    }


class FakeAnam:
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []
        self.sessions: list[dict] = []  # what Anam's account says was used
        self.list_fails = False

    def get(self, url, *, headers, params=None, timeout=None):
        if self.list_fails:
            raise httpx.ConnectError("down")
        body = {"data": self.sessions, "meta": {"total": len(self.sessions)}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    def post(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json})
        body = {"sessionToken": "anam-session-token-for-test"} if self.status == 200 else {}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def anam(monkeypatch):
    fake = FakeAnam()
    monkeypatch.setenv("ANAM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANAM_MONTHLY_MINUTE_CAP", "30")
    monkeypatch.delenv("ANAM_RESET_DAY", raising=False)
    monkeypatch.setattr(avatar.httpx, "post", fake.post)
    monkeypatch.setattr(avatar.httpx, "get", fake.get)
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
    cfg = agent1.get("/api/config").json()["avatar"]
    assert cfg == {"sdk": avatar.SDK_VERSION, "minutes_left": 30, "minutes_total": 30}
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


def test_minutes_left_come_from_anams_own_usage(anam, agent1):
    now = datetime.now(UTC)
    anam.sessions = [
        _session(now - timedelta(minutes=5), 180),
        _session(now - timedelta(hours=1), 120),
    ]
    avatar.reset_for_tests()
    cfg = agent1.get("/api/config").json()["avatar"]
    assert cfg["minutes_left"] == 25 and cfg["minutes_total"] == 30


def test_a_call_is_never_blocked_by_a_reservation(anam, agent1):
    """Only minutes really used count. A call planned for 7 minutes still starts with 5 left."""
    now = datetime.now(UTC)
    anam.sessions = [_session(now - timedelta(minutes=5), 25 * 60)]
    avatar.reset_for_tests()
    sid = _start(agent1)
    assert agent1.post(f"/api/sessions/{sid}/avatar").status_code == 200
    assert anam.calls[0]["json"]["personaConfig"]["maxSessionLengthSeconds"] <= 5 * 60


def test_no_video_once_the_free_minutes_are_used_up(anam, agent1):
    now = datetime.now(UTC)
    anam.sessions = [_session(now - timedelta(minutes=5), 30 * 60)]
    avatar.reset_for_tests()
    cfg = agent1.get("/api/config").json()
    assert cfg["avatar"] is None and cfg["video_minutes"]["minutes_left"] == 0
    assert agent1.post(f"/api/sessions/{_start(agent1)}/avatar").status_code == 204


def test_without_a_key_there_is_no_counter(agent1):
    assert agent1.get("/api/config").json()["video_minutes"] is None


def test_minutes_reset_on_the_plans_reset_day(anam, agent1, monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setenv("ANAM_RESET_DAY", str(now.day))  # the plan renewed this morning
    anam.sessions = [_session(now - timedelta(days=3), 20 * 60)]
    avatar.reset_for_tests()
    assert agent1.get("/api/config").json()["avatar"]["minutes_left"] == 30


def test_if_anam_cannot_be_asked_our_own_record_is_used(anam, agent1):
    sid = _start(agent1)
    agent1.post(f"/api/sessions/{sid}/avatar")  # records the planned minutes
    anam.list_fails = True
    avatar.reset_for_tests()
    cfg = agent1.get("/api/config").json()["avatar"]
    assert cfg is not None and cfg["minutes_left"] < 30


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

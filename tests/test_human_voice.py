"""Human voice for the customer (ElevenLabs Flash v2.5), with a monthly cap and a browser fallback."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import events, usage, voice

SCENARIO = "price-worried-owner"
MP3 = b"ID3fake-mp3-bytes"


class FakeEleven:
    """Stands in for ElevenLabs: records each request, answers with a status and bytes."""

    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, *, headers, params, json, timeout):
        self.calls.append({"url": url, "headers": headers, "params": params, "json": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            self.status, content=MP3 if self.status == 200 else b"{}", request=request
        )


@pytest.fixture
def eleven(monkeypatch):
    fake = FakeEleven()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    monkeypatch.setattr(voice.httpx, "post", fake.post)
    voice.reset_for_tests()
    usage.reset_for_tests()
    yield fake
    voice.reset_for_tests()


def _call_with_reply(c) -> str:
    sid = c.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    c.post(f"/api/sessions/{sid}/turns", json={"text": "Hi Maria, how do you keep your books?"})
    return sid


def test_customer_line_comes_back_as_human_audio(eleven, agent1):
    sid = _call_with_reply(agent1)
    res = agent1.get(f"/api/sessions/{sid}/voice/1")
    assert res.status_code == 200 and res.headers["content-type"] == "audio/mpeg"
    assert res.content == MP3
    sent = eleven.calls[0]
    assert sent["json"]["model_id"] == "eleven_flash_v2_5"
    assert sent["headers"]["xi-api-key"] == "test-key-not-real"
    assert sent["url"].rsplit("/", 1)[-1] in voice.all_voice_ids()


def test_only_the_customers_words_are_sent(eleven, agent1):
    sid = _call_with_reply(agent1)
    agent1.get(f"/api/sessions/{sid}/voice/1")
    customer_line = agent1.get(f"/api/sessions/{sid}").json()["turns"][1]["customer_text"]
    assert eleven.calls[0]["json"]["text"] == customer_line
    assert "how do you keep your books" not in eleven.calls[0]["json"]["text"].lower()


def test_opening_line_is_cached(eleven, agent1, agent2):
    for c in (agent1, agent2):
        sid = c.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
        assert c.get(f"/api/sessions/{sid}/voice/0").status_code == 200
    assert len(eleven.calls) == 1


def test_characters_are_counted_against_the_monthly_cap(eleven, monkeypatch, agent1):
    sid = _call_with_reply(agent1)
    before = voice.characters_this_month()
    agent1.get(f"/api/sessions/{sid}/voice/1")
    used = voice.characters_this_month() - before
    assert used == len(eleven.calls[0]["json"]["text"])
    monkeypatch.setenv("ELEVENLABS_MONTHLY_CHAR_CAP", str(voice.characters_this_month()))
    sid2 = _call_with_reply(agent1)
    assert agent1.get(f"/api/sessions/{sid2}/voice/1").status_code == 204  # page uses browser voice
    assert agent1.get("/api/config").json()["voice"] == "browser"


def test_elevenlabs_refusal_falls_back_and_stops_asking(eleven, agent1):
    eleven.status = 401  # bad key or quota used up
    sid = _call_with_reply(agent1)
    assert agent1.get(f"/api/sessions/{sid}/voice/1").status_code == 204
    assert agent1.get(f"/api/sessions/{sid}/voice/0").status_code == 204
    assert len(eleven.calls) == 1  # no more requests this month after a refusal
    recent = events.since(datetime.now(UTC) - timedelta(minutes=5), "fallback")
    assert any(r["name"] == "voice.elevenlabs" and r["detail"] == "refused 401" for r in recent)


def test_without_a_key_the_browser_voice_is_used(agent1, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    voice.reset_for_tests()
    assert agent1.get("/api/config").json()["voice"] == "browser"
    sid = _call_with_reply(agent1)
    assert agent1.get(f"/api/sessions/{sid}/voice/1").status_code == 204


def test_voice_follows_the_call_owner(eleven, agent1, agent2):
    sid = _call_with_reply(agent1)
    assert agent2.get(f"/api/sessions/{sid}/voice/1").status_code == 404
    assert agent1.get(f"/api/sessions/{sid}/voice/9").status_code == 404


def test_voice_matches_the_customer_and_mood():
    meera = {"name": "Maria", "voice": "female", "mood": "Cautious"}
    rahul = {"name": "Mike", "voice": "male", "mood": "Frustrated"}
    assert voice.pick_voice(meera) in voice.VOICES["female"]
    assert voice.pick_voice(rahul) in voice.VOICES["male"]
    assert voice.pick_voice(meera) == voice.pick_voice(meera)  # same customer, same voice
    assert voice.settings_for(rahul)["stability"] < voice.settings_for(meera)["stability"]
    assert voice.pick_voice({"name": "Sam"}) in voice.all_voice_ids()

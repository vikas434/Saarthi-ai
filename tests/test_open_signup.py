"""Open sign-up (OPEN_SIGNUP=1): anyone signed in is an agent; the admin sees who joined."""

import pytest
from fastapi.testclient import TestClient

from app import auth, limits, usage
from app.main import app

SCENARIO = "price-worried-owner"


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "1")
    auth.reset_for_tests()
    yield
    auth.reset_for_tests()


def _as(email: str) -> TestClient:
    return TestClient(app, headers={"X-Dev-User": email})


def test_new_person_is_an_agent_when_sign_up_is_open(open_signup):
    newcomer = _as("New.Person@Open.example.com")
    assert newcomer.get("/api/me").json() == {
        "email": "new.person@open.example.com",
        "role": "agent",
    }
    assert newcomer.post("/api/sessions", json={"scenario_id": SCENARIO}).status_code == 200


def test_open_sign_up_never_makes_anyone_admin(open_signup):
    newcomer = _as("someone@open.example.com")
    assert newcomer.put("/api/product", json={"text": "x" * 40}).status_code == 403
    assert newcomer.get("/api/access-requests").status_code == 403
    assert newcomer.get("/api/config").json()["role"] == "agent"


def test_admin_sees_who_joined(open_signup, client):
    _as("joiner@open.example.com").get("/api/me")
    emails = [r["email"] for r in client.get("/api/access-requests").json()]
    assert "joiner@open.example.com" in emails
    assert client.get("/api/config").json()["open_signup"] is True


def test_newcomers_cannot_see_each_others_calls(open_signup):
    first, second = _as("first@open.example.com"), _as("second@open.example.com")
    sid = first.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    assert second.get(f"/api/sessions/{sid}").status_code == 404
    assert all(s["id"] != sid for s in second.get("/api/sessions").json())


def test_sign_up_is_closed_by_default(client):
    res = _as("closed@elsewhere.example.com").get("/api/me")
    assert res.status_code == 403 and res.json()["detail"] == auth.ACCESS_PENDING
    assert client.get("/api/config").json()["open_signup"] is False


def test_config_tells_each_person_their_calls_left_today(monkeypatch, open_signup):
    limits.reset_for_tests()
    usage.reset_for_tests()
    person = _as("counter@open.example.com")
    monkeypatch.setenv("MAX_CALLS_PER_USER_PER_DAY", "3")
    before = person.get("/api/config").json()
    assert before["calls_per_day"] == 3 and before["calls_left"] == 3
    person.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert person.get("/api/config").json()["calls_left"] == 2


def test_limit_messages_are_friendly_and_name_the_number(monkeypatch, open_signup):
    person = _as("busy@open.example.com")
    monkeypatch.setenv("MAX_CALLS_PER_USER_PER_DAY", "1")
    person.post("/api/sessions", json={"scenario_id": SCENARIO})
    blocked = person.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert "1 practice call" in detail and "tomorrow" in detail and "limit reached" in detail

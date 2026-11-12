"""Personal dashboard (focus metrics over time, streak, insights) and the admin's team view."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import auth, dashboard
from app.main import app

SCENARIO = "price-worried-owner"
WEAK = ["Um, so basically you should just buy it today, you know."]
STRONG = [
    "Hi Meera, thanks for calling. How do you keep your books today?",
    "That sounds tiring. What would make Sunday evenings easier for you?",
]


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "1")
    auth.reset_for_tests()
    yield
    auth.reset_for_tests()


def _person(email: str) -> TestClient:
    return TestClient(app, headers={"X-Dev-User": email})


def _scored_call(c: TestClient, lines: list[str]) -> None:
    sid = c.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    for line in lines:
        c.post(f"/api/sessions/{sid}/turns", json={"text": line})
    assert c.post(f"/api/sessions/{sid}/end").status_code == 200


def test_new_person_sees_an_empty_dashboard_with_default_focus(open_signup):
    board = _person("fresh@dash.example.com").get("/api/dashboard").json()
    assert len(board["focus"]) == 4 and "overall" in board["focus"]
    ids = {m["id"] for m in board["catalog"]}
    assert {"overall", "filler_words", "pace", "talk_time", "questions", "marker:tnps"} <= ids
    assert all(board["series"][m] == [] for m in board["focus"])
    assert board["streak"] == 0 and board["calls"] == 0
    assert board["insights"] == ["Finish a practice call to see your trends here."]


def test_scored_calls_become_points_over_time(open_signup):
    person = _person("trend@dash.example.com")
    _scored_call(person, WEAK)
    _scored_call(person, STRONG)
    board = person.get("/api/dashboard").json()
    overall = board["series"]["overall"]
    assert len(overall) == 2 and all(0 <= p["value"] <= 100 for p in overall)
    assert board["series"]["filler_words"][0]["value"] > board["series"]["filler_words"][1]["value"]
    assert board["streak"] == 1 and board["calls"] == 2 and board["calls_this_week"] == 2
    assert any("overall score" in i for i in board["insights"])


def test_unscored_calls_and_tutor_sessions_are_left_out(open_signup):
    person = _person("partial@dash.example.com")
    person.post("/api/sessions", json={"scenario_id": SCENARIO})
    person.post("/api/tutor", json={"scenario_id": SCENARIO})
    assert person.get("/api/dashboard").json()["calls"] == 0


def test_focus_is_chosen_per_person(open_signup):
    person = _person("focus@dash.example.com")
    res = person.put("/api/dashboard/focus", json={"metrics": ["pace", "marker:tnps"]})
    assert res.status_code == 200
    assert person.get("/api/dashboard").json()["focus"] == ["pace", "marker:tnps"]
    other = _person("other@dash.example.com").get("/api/dashboard").json()["focus"]
    assert other != ["pace", "marker:tnps"]


@pytest.mark.parametrize(
    "metrics",
    [["nope"], ["pace", "overall", "questions", "talk_time", "filler_words"], []],
)
def test_focus_must_be_one_to_four_known_metrics(open_signup, metrics):
    res = _person("bad@dash.example.com").put("/api/dashboard/focus", json={"metrics": metrics})
    assert res.status_code == 422


def test_streak_counts_consecutive_practice_days():
    today = date(2026, 11, 12)
    days = {date(2026, 11, 12), date(2026, 11, 11), date(2026, 11, 10), date(2026, 11, 7)}
    assert dashboard.streak(days, today) == 3
    assert dashboard.streak({date(2026, 11, 11), date(2026, 11, 10)}, today) == 2  # yesterday
    assert dashboard.streak({date(2026, 11, 10)}, today) == 0
    assert dashboard.streak(set(), today) == 0


def test_team_view_is_for_the_admin(open_signup, client):
    person = _person("teammate@dash.example.com")
    _scored_call(person, WEAK)
    _scored_call(person, STRONG)
    assert person.get("/api/team").status_code == 403
    rows = client.get("/api/team").json()
    mine = next(r for r in rows if r["name"] == "teammate")
    assert mine["calls"] == 2 and mine["first"] is not None and mine["latest"] is not None
    assert mine["change"] == mine["latest"] - mine["first"]
    assert "email" not in mine

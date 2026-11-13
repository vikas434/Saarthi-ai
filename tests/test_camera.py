"""The agent's camera: per-reply numbers only (never images), and the On camera analytics."""

import pytest

from app import delivery

SCENARIO = "price-worried-owner"


def _camera(**over):
    base = {"frames": 40, "face_pct": 100.0, "eye_contact_pct": 80.0, "smile_pct": 20.0,
            "tense_pct": 5.0}  # fmt: skip
    return {**base, **over}


def test_camera_numbers_are_stored_per_reply_and_scored(agent1):
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    agent1.post(
        f"/api/sessions/{sid}/turns",
        json={"text": "Hi Meera, how do you keep your books?", "camera": _camera()},
    )
    agent1.post(
        f"/api/sessions/{sid}/turns",
        json={"text": "What would make Sundays easier?", "camera": _camera(eye_contact_pct=20.0)},
    )
    report = agent1.post(f"/api/sessions/{sid}/end").json()
    turns = [t for t in report["turns"] if t["agent_text"]]
    assert turns[0]["camera"]["eye_contact_pct"] == 80.0
    camera = {
        m["id"]: m for m in report["report"]["analytics"]["metrics"] if m["group"] == "camera"
    }
    assert camera["eye_contact"]["percent"] == 50.0  # frame-weighted
    assert camera["eye_contact"]["verdict"] == "watch"
    assert "reply 2" in camera["eye_contact"]["detail"]
    assert camera["smile"]["verdict"] == "good"


def test_calls_without_camera_have_no_camera_section(agent1):
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hello Meera"})
    report = agent1.post(f"/api/sessions/{sid}/end").json()["report"]
    assert report["analytics"]["camera"] is False
    assert not [m for m in report["analytics"]["metrics"] if m["group"] == "camera"]


@pytest.mark.parametrize(
    "bad",
    [
        {"frames": 10, "face_pct": 120, "eye_contact_pct": 1, "smile_pct": 1, "tense_pct": 1},
        {"frames": -1, "face_pct": 1, "eye_contact_pct": 1, "smile_pct": 1, "tense_pct": 1},
        {"frames": 10, "face_pct": 1, "eye_contact_pct": 1, "smile_pct": 1},
        {
            "frames": 10,
            "face_pct": 1,
            "eye_contact_pct": 1,
            "smile_pct": 1,
            "tense_pct": 1,
            "image": "data:image/png;base64,AAAA",
        },
    ],
)
def test_only_well_formed_numbers_are_accepted(agent1, bad):
    sid = agent1.post("/api/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    res = agent1.post(f"/api/sessions/{sid}/turns", json={"text": "Hello", "camera": bad})
    if "image" in bad:  # extra fields are dropped, never stored
        assert res.status_code == 200
        session = agent1.get(f"/api/sessions/{sid}").json()
        assert "image" not in (session["turns"][-1]["camera"] or {})
    else:
        assert res.status_code == 422


def test_metrics_reward_eye_contact_smiles_and_a_relaxed_face():
    turns = [
        {
            "agent_text": "Hi",
            "customer_text": "Hello",
            "camera": _camera(tense_pct=40.0, smile_pct=0.0),
        }
    ]
    got = {
        m["id"]: m["verdict"] for m in delivery.analyze(turns)["metrics"] if m["group"] == "camera"
    }
    assert got == {
        "eye_contact": "good",
        "smile": "watch",
        "tense_face": "watch",
        "face_in_frame": "good",
    }

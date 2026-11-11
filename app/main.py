"""Saarthi API and the single-page app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import coach, store

app = FastAPI(title="Saarthi", version="0.1.0")
STATIC = Path(__file__).parent / "static"


class StartIn(BaseModel):
    scenario_id: str
    agent_name: str = Field(default="Agent", max_length=80)


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ProductIn(BaseModel):
    text: str = Field(min_length=20, max_length=20000)


class MarkerIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    type: str = Field(pattern="^(rubric|survey|checklist)$")
    lines: list[str] = Field(default_factory=list, max_length=40)
    question: str = Field(default="", max_length=300)
    min: int = 1
    max: int = 5


class ScenarioIn(BaseModel):
    description: str = Field(min_length=5, max_length=500)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict:
    return {
        "mode": coach.mode(),
        "rubric": coach.load_rubric(),
        "markers": coach.load_markers(),
        "scenarios": [coach.public_scenario(s) for s in coach.load_scenarios()],
        "product": coach.load_product(),
    }


@app.put("/api/product")
def set_product(body: ProductIn) -> dict:
    store.set_kv("product", body.text)
    return {"saved": True}


@app.post("/api/scenarios")
def add_scenario(body: ScenarioIn) -> dict:
    scenario = coach.draft_scenario(body.description)
    store.save_scenario(scenario)
    return coach.public_scenario(scenario)


@app.post("/api/markers")
def add_marker(body: MarkerIn) -> dict:
    """Add a rubric, survey or checklist marker. It is scored on every call from then on."""
    try:
        return coach.add_marker(
            body.name, body.type, body.lines, question=body.question, lo=body.min, hi=body.max
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/markers/{marker_id}")
def delete_marker(marker_id: str) -> dict:
    if not coach.remove_marker(marker_id):
        raise HTTPException(status_code=404, detail="Only markers added in Setup can be removed")
    return {"removed": True}


def _session_or_404(sid: str) -> dict:
    session = store.get_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/sessions")
def start(body: StartIn) -> dict:
    scenario = coach.get_scenario(body.scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    sid = store.create_session(
        scenario["id"], body.agent_name.strip() or "Agent", scenario["opening_line"], coach.mode()
    )
    return {
        "id": sid,
        "scenario": coach.public_scenario(scenario),
        "customer": scenario["opening_line"],
    }


@app.post("/api/sessions/{sid}/turns")
def turn(sid: str, body: TurnIn) -> dict:
    session = _session_or_404(sid)
    if session["report"] is not None or session["done"]:
        raise HTTPException(status_code=409, detail="This call has ended. Get the scorecard.")
    result = coach.next_turn(session, body.text.strip())
    store.add_turn(sid, body.text.strip(), result["customer"], result["coach"], result["done"])
    return result


@app.post("/api/sessions/{sid}/end")
def end(sid: str) -> dict:
    session = _session_or_404(sid)
    if session["report"] is None:
        if not any(t["agent_text"] for t in session["turns"]):
            raise HTTPException(status_code=400, detail="Say something to the customer first.")
        store.save_report(sid, coach.build_report(session))
        session = _session_or_404(sid)
    return session


@app.get("/api/sessions")
def sessions() -> list[dict]:
    titles = {s["id"]: s["title"] for s in coach.load_scenarios()}
    return [
        {**s, "scenario_title": titles.get(s["scenario_id"], s["scenario_id"])}
        for s in store.list_sessions()
    ]


@app.get("/api/sessions/{sid}")
def session(sid: str) -> dict:
    return _session_or_404(sid)


@app.get("/api/progress")
def progress() -> dict:
    return coach.progress()

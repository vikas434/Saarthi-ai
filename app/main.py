"""Saarthi API and the single-page app. Every /api route except /api/auth/config needs sign-in."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app import auth, coach, db, limits, store, usage
from app.auth import AuthError, Principal
from app.limits import LimitReached
from app.web_security import SecurityMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Migrate on start, so a broken database fails the deploy instead of the first visitor."""
    db.engine()
    yield


app = FastAPI(
    title="Saarthi",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SecurityMiddleware)
STATIC = Path(__file__).parent / "static"


class StartIn(BaseModel):
    scenario_id: str
    agent_name: str = Field(default="", max_length=80)


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # How long the agent spoke, for spoken replies only.
    seconds: float | None = Field(default=None, ge=0, le=600)


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


@app.exception_handler(AuthError)
def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return JSONResponse({"detail": exc.detail}, status_code=exc.status, headers=headers)


@app.exception_handler(LimitReached)
def _limit_reached(_: Request, exc: LimitReached) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=429)


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    user = auth.authenticate(authorization, x_dev_user)
    limits.check_rate(user.user_id)
    return user


def admin_user(user: Annotated[Principal, Depends(current_user)]) -> Principal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can change Setup.")
    return user


User = Annotated[Principal, Depends(current_user)]
Admin = Annotated[Principal, Depends(admin_user)]


@app.get("/health")
def health() -> dict:
    """Alive: the process answers."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    """Ready: the database answers too."""
    if db.ping():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "database unreachable"}, status_code=503)


@app.get("/")
def index() -> FileResponse:
    # Always revalidate, so a new deploy is seen on the next load.
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# Scripts next to the single page: voice for calls, and the scorecard view.
PAGE_SCRIPTS = frozenset({"voice", "report"})


@app.get("/{name}.js")
def page_script(name: str) -> FileResponse:
    if name not in PAGE_SCRIPTS:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        STATIC / f"{name}.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/auth/config")
def auth_config() -> dict:
    """Public: how the page should sign people in. No secrets."""
    return auth.public_config()


@app.get("/api/me")
def me(user: User) -> dict:
    return {"email": user.email, "role": user.role}


@app.get("/api/config")
def config(user: User) -> dict:
    return {
        "mode": coach.mode(),
        "role": user.role,
        "open_signup": auth.open_signup(),
        "calls_per_day": limits.calls_per_day(),
        "calls_left": limits.calls_left(user.user_id),
        "rubric": coach.load_rubric(),
        "markers": coach.load_markers(),
        "scenarios": [coach.public_scenario(s) for s in coach.load_scenarios()],
        "product": coach.load_product(),
    }


@app.put("/api/product")
def set_product(body: ProductIn, _: Admin) -> dict:
    store.set_kv("product", body.text)
    return {"saved": True}


@app.post("/api/scenarios")
def add_scenario(body: ScenarioIn, user: Admin) -> dict:
    with usage.attribute(session_id=None, user_id=user.user_id):
        scenario = coach.draft_scenario(body.description)
    store.save_scenario(scenario)
    return coach.public_scenario(scenario)


@app.post("/api/markers")
def add_marker(body: MarkerIn, _: Admin) -> dict:
    """Add a rubric, survey or checklist marker. It is scored on every call from then on."""
    try:
        return coach.add_marker(
            body.name, body.type, body.lines, question=body.question, lo=body.min, hi=body.max
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/markers/{marker_id}")
def delete_marker(marker_id: str, _: Admin) -> dict:
    if not coach.remove_marker(marker_id):
        raise HTTPException(status_code=404, detail="Only markers added in Setup can be removed")
    return {"removed": True}


@app.get("/api/access-requests")
def access_requests(_: Admin) -> list[dict]:
    """Sign-ins from emails outside the allow-list: newcomers with OPEN_SIGNUP, else requests."""
    return store.list_access_requests()


def _owner_filter(user: Principal) -> str | None:
    """None means every call (admin); otherwise only the caller's own."""
    return None if user.role == "admin" else user.user_id


def _session_or_404(sid: str, user: Principal) -> dict:
    session = store.get_session(sid)
    owner = _owner_filter(user)
    if session is None or (owner is not None and session.get("user_id") != owner):
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _for_viewer(session: dict, user: Principal) -> dict:
    """The admin also sees what the call cost."""
    if user.role != "admin":
        return session
    return {**session, "cost_usd": usage.session_cost(session["id"])}


@app.post("/api/sessions")
def start(body: StartIn, user: User) -> dict:
    scenario = coach.get_scenario(body.scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    limits.check_new_call(user.user_id)
    name = body.agent_name.strip() or user.email.split("@", 1)[0]
    sid = store.create_session(
        scenario["id"], name, scenario["opening_line"], coach.mode(), user_id=user.user_id
    )
    return {
        "id": sid,
        "scenario": coach.public_scenario(scenario),
        "customer": scenario["opening_line"],
    }


@app.post("/api/sessions/{sid}/turns")
def turn(sid: str, body: TurnIn, user: User) -> dict:
    session = _session_or_404(sid, user)
    if session["report"] is not None or session["done"]:
        raise HTTPException(status_code=409, detail="This call has ended. Get the scorecard.")
    if sum(1 for t in session["turns"] if t["agent_text"]) >= limits.max_replies_per_call():
        raise HTTPException(
            status_code=409,
            detail="This call reached its reply limit. End it to get the scorecard.",
        )
    with usage.attribute(session_id=sid, user_id=user.user_id):
        result = coach.next_turn(session, body.text.strip())
    store.add_turn(
        sid,
        body.text.strip(),
        result["customer"],
        result["coach"],
        result["done"],
        agent_seconds=body.seconds,
    )
    return result


@app.post("/api/sessions/{sid}/end")
def end(sid: str, user: User) -> dict:
    session = _session_or_404(sid, user)
    if session["report"] is None:
        if not any(t["agent_text"] for t in session["turns"]):
            raise HTTPException(status_code=400, detail="Say something to the customer first.")
        with usage.attribute(session_id=sid, user_id=user.user_id):
            report = coach.build_report(session)
        store.save_report(sid, report)
        session = _session_or_404(sid, user)
    return _for_viewer(session, user)


@app.get("/api/sessions")
def sessions(user: User) -> list[dict]:
    titles = {s["id"]: s["title"] for s in coach.load_scenarios()}
    return [
        {**s, "scenario_title": titles.get(s["scenario_id"], s["scenario_id"])}
        for s in store.list_sessions(_owner_filter(user))
    ]


@app.get("/api/sessions/{sid}")
def session(sid: str, user: User) -> dict:
    return _for_viewer(_session_or_404(sid, user), user)


@app.get("/api/progress")
def progress(user: User) -> dict:
    return coach.progress(_owner_filter(user))

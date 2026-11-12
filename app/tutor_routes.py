"""Routes for tutor mode. A tutor session counts as a practice call toward the daily limit."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import coach, limits, roleplays, store, tutor, usage
from app.auth import Principal
from app.deps import User

router = APIRouter(prefix="/api/tutor")
NOT_FOUND = "Tutor session not found"
TUTOR_OPENING = "Tutor lesson"


class TutorIn(BaseModel):
    scenario_id: str


class AnswerIn(BaseModel):
    index: int = Field(ge=0, lt=tutor.QUESTIONS)
    text: str = Field(min_length=1, max_length=2000)


def _own_tutor(sid: str, user: Principal) -> tuple[dict, dict]:
    """The learner's own tutor session and its plan, or 404."""
    session = store.get_session(sid)
    if session is None or session.get("kind") != "tutor" or session["user_id"] != user.user_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    plan = store.get_plan(sid)
    if plan is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return session, plan


@router.post("")
def start_tutor(body: TutorIn, user: User) -> dict:
    scenario = coach.get_scenario(body.scenario_id)
    if scenario is None or not roleplays.can_use(scenario, user):
        raise HTTPException(status_code=404, detail="Scenario not found")
    limits.check_new_call(user.user_id)
    name = user.email.split("@", 1)[0]
    sid = store.create_session(
        scenario["id"], name, TUTOR_OPENING, coach.mode(), user_id=user.user_id, kind="tutor"
    )
    with usage.attribute(session_id=sid, user_id=user.user_id):
        plan = tutor.lesson(scenario)
    store.set_plan(sid, plan)
    return tutor.public(sid, plan)


@router.post("/{sid}/answers")
def answer(sid: str, body: AnswerIn, user: User) -> dict:
    session, plan = _own_tutor(sid, user)
    if session["done"] or plan["answers"][body.index] is not None:
        raise HTTPException(status_code=409, detail="That question has been answered.")
    with usage.attribute(session_id=sid, user_id=user.user_id):
        result = tutor.grade(plan, body.index, body.text.strip())
    store.set_plan(sid, tutor.with_answer(plan, body.index, body.text.strip(), result))
    return result


@router.post("/{sid}/end")
def end(sid: str, user: User) -> dict:
    session, plan = _own_tutor(sid, user)
    if session["report"] is not None:
        return session["report"]
    report = tutor.finish(plan)
    store.save_report(sid, report)
    return report

"""Routes for the personal dashboard and the admin's team view."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import dashboard
from app.deps import Admin, User

router = APIRouter(prefix="/api")


class FocusIn(BaseModel):
    metrics: list[str] = Field(max_length=10)


@router.get("/dashboard")
def my_dashboard(user: User) -> dict:
    return dashboard.for_user(user.user_id)


@router.put("/dashboard/focus")
def choose_focus(body: FocusIn, user: User) -> dict:
    try:
        return {"focus": dashboard.set_focus(user.user_id, body.metrics)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/team")
def team(_: Admin) -> list[dict]:
    return dashboard.team()

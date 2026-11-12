"""Routes for the roleplay builder and personas. Every route needs sign-in."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import roleplays, store, usage
from app.deps import Admin, User
from app.roleplays import PersonaIn, RoleplayIn

router = APIRouter(prefix="/api")
NOT_FOUND = "Roleplay not found"


class DraftIn(BaseModel):
    description: str = Field(min_length=5, max_length=1000)


class PublishIn(BaseModel):
    published: bool


@router.get("/roleplays/templates")
def roleplay_templates(_: User) -> list[dict]:
    return roleplays.templates()


@router.post("/roleplays/draft")
def draft_roleplay(body: DraftIn, user: User) -> dict:
    """An AI draft to review and edit. Not saved until the person saves it."""
    roleplays.check_draft_allowed()
    with usage.attribute(session_id=None, user_id=user.user_id):
        return roleplays.draft(body.description)


@router.post("/roleplays")
def create_roleplay(body: RoleplayIn, user: User) -> dict:
    return roleplays.create(body, user)


@router.get("/roleplays/{roleplay_id}")
def get_roleplay(roleplay_id: str, user: User) -> dict:
    found = roleplays.editable(roleplay_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return roleplays.full(found)


@router.put("/roleplays/{roleplay_id}")
def update_roleplay(roleplay_id: str, body: RoleplayIn, user: User) -> dict:
    found = roleplays.editable(roleplay_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return roleplays.update(found, body)


@router.delete("/roleplays/{roleplay_id}")
def delete_roleplay(roleplay_id: str, user: User) -> dict:
    if roleplays.editable(roleplay_id, user) is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    store.delete_scenario(roleplay_id)
    return {"deleted": True}


@router.post("/roleplays/{roleplay_id}/publish")
def publish_roleplay(roleplay_id: str, body: PublishIn, _: Admin) -> dict:
    """Admin only: share a saved roleplay with everyone, or take it back to its builder."""
    found = roleplays.coach.get_scenario(roleplay_id)
    if found is None or roleplays.is_built_in(found):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    store.set_scenario_visibility(roleplay_id, "published" if body.published else "private")
    return {"published": body.published}


@router.get("/personas")
def list_personas(user: User) -> list[dict]:
    return roleplays.personas(user)


@router.post("/personas")
def create_persona(body: PersonaIn, user: User) -> dict:
    return roleplays.save_persona(body, user)


@router.delete("/personas/{persona_id}")
def delete_persona(persona_id: str, user: User) -> dict:
    if not store.delete_persona(persona_id, user.user_id):
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"deleted": True}

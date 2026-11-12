"""Roleplay builder: templates, AI drafts, private roleplays, publishing, and personas.

A roleplay is the scenario a practice call runs on. Built-in ones come from config; people build
their own, which only they can see until the admin publishes one to everyone. The full roleplay,
with its hidden objections, is only ever sent to its builder (and the admin, for published ones).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app import coach, events, limits, schemas, store, usage
from app.auth import Principal
from app.config import env
from app.limits import LimitReached
from app.llm import get_llm

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROLEPLAYS_PER_USER = 20
DEFAULT_MAX_PERSONAS_PER_USER = 20
DEFAULT_GOALS = [
    {
        "name": "Understand their needs",
        "description": "Ask about their situation first",
        "weight": 2,
    },
    {
        "name": "Agree a next step",
        "description": "End with a specific, agreed next step",
        "weight": 1,
    },
]


class Goal(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    weight: int = Field(default=1, ge=1, le=5)


class Customer(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(default="", max_length=80)
    voice: Literal["", "female", "male"] = ""
    persona: str = Field(default="", max_length=1000)
    mood: str = Field(default="", max_length=60)
    situation: str = Field(default="", max_length=1500)
    hidden_objections: list[str] = Field(default_factory=list, max_length=15)
    wins_if: str = Field(default="", max_length=500)
    walks_away_if: str = Field(default="", max_length=500)


class RoleplayIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    difficulty: Literal["Easy", "Medium", "Hard"] = "Medium"
    public_brief: str = Field(min_length=5, max_length=500)
    customer: Customer
    opening_line: str = Field(min_length=1, max_length=300)
    minutes: int = Field(default=coach.DEFAULT_CALL_MINUTES, ge=2, le=20)
    goals: list[Goal] = Field(default_factory=list, max_length=6)


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(default="", max_length=80)
    voice: Literal["", "female", "male"] = ""
    mood: str = Field(default="", max_length=60)
    background: str = Field(default="", max_length=1000)


def _int_env(name: str, default: int) -> int:
    try:
        return int(env(name) or default)
    except ValueError:
        return default


def _load_config(name: str) -> list[dict]:
    return json.loads((coach.CONFIG_DIR / name).read_text(encoding="utf-8"))


def templates() -> list[dict]:
    return _load_config("templates.json")


# Access


def is_built_in(scenario: dict) -> bool:
    return "visibility" not in scenario


def is_published(scenario: dict) -> bool:
    return is_built_in(scenario) or scenario.get("visibility") == "published"


def is_owner(scenario: dict, user: Principal) -> bool:
    return bool(scenario.get("owner_id")) and scenario["owner_id"] == user.user_id


def can_use(scenario: dict, user: Principal) -> bool:
    return is_published(scenario) or is_owner(scenario, user)


def can_edit(scenario: dict, user: Principal) -> bool:
    """The builder edits their own; the admin also edits the team's saved roleplays."""
    if is_built_in(scenario):
        return False
    return is_owner(scenario, user) or (user.role == "admin" and is_published(scenario))


def view(scenario: dict, user: Principal) -> dict:
    """The card a person sees in the library: never the hidden objections."""
    return {
        **coach.public_scenario(scenario),
        "mine": is_owner(scenario, user),
        "published": is_published(scenario),
        "built_in": is_built_in(scenario),
    }


def library(user: Principal) -> list[dict]:
    return [view(s, user) for s in coach.load_scenarios() if can_use(s, user)]


def editable(roleplay_id: str, user: Principal) -> dict | None:
    s = coach.get_scenario(roleplay_id)
    return s if s is not None and can_edit(s, user) else None


def full(scenario: dict) -> dict:
    """The whole roleplay for its editor, without storage fields."""
    out = {k: v for k, v in scenario.items() if k not in ("owner_id",)}
    out["published"] = is_published(scenario)
    return out


# Building


def create(body: RoleplayIn, user: Principal) -> dict:
    cap = _int_env("MAX_ROLEPLAYS_PER_USER", DEFAULT_MAX_ROLEPLAYS_PER_USER)
    if store.count_scenarios(user.user_id) >= cap:
        raise LimitReached(f"You can keep up to {cap} roleplays. Delete one to make room.")
    scenario = {"id": f"rp-{uuid.uuid4().hex[:10]}", **body.model_dump()}
    store.save_scenario(scenario, owner_id=user.user_id, visibility="private")
    return full(coach.get_scenario(scenario["id"]))


def update(existing: dict, body: RoleplayIn) -> dict:
    scenario = {"id": existing["id"], **body.model_dump()}
    store.save_scenario(
        scenario, owner_id=existing.get("owner_id"), visibility=existing["visibility"]
    )
    return full(coach.get_scenario(existing["id"]))


def _basic_draft(description: str) -> dict:
    text = description.strip()
    return {
        "title": text[:60],
        "difficulty": "Medium",
        "public_brief": text[:500],
        "customer": {
            "name": "Alex",
            "role": "",
            "persona": text,
            "mood": "Neutral",
            "situation": "Wants to know if the product fits.",
            "hidden_objections": [
                "Not sure it is worth the price",
                "Worried about the effort to switch",
            ],
            "wins_if": "The agent asks about their needs and answers honestly.",
            "walks_away_if": "The agent pushes or ignores their concerns.",
        },
        "opening_line": "Hi, I had a few questions before I decide.",
        "minutes": coach.DEFAULT_CALL_MINUTES,
        "goals": [dict(g) for g in DEFAULT_GOALS],
    }


DRAFT_SYSTEM = """Draft a sales practice roleplay as JSON only, with keys: title (under 60
characters), difficulty (Easy|Medium|Hard), public_brief (what the agent is told, 1-2 sentences),
customer {name, role, voice (female or male), persona, mood (one word), situation, hidden_objections (3 strings the
customer will not volunteer), wins_if, walks_away_if}, opening_line (the customer's first words),
minutes (3 to 10), goals (2 or 3 of {name (2-4 words), description (one sentence), weight 1-3}).
The customer may only know what a real customer would; base product details on the product facts.

Product facts:
"""


def draft(description: str) -> dict:
    """Turn a description into a full roleplay to review. Not saved."""
    out = _basic_draft(description)
    llm = get_llm()
    if llm is None:
        return out
    try:
        with usage.kind("draft"):
            data = coach.ask_model(
                llm,
                system=DRAFT_SYSTEM + coach.load_product(),
                user=f"Roleplay to draft: {description}\n\nJSON:",
                max_tokens=coach.SCENARIO_MAX_TOKENS,
                schema=schemas.scenario_schema(),
            )
        merged = {**out, **{k: v for k, v in data.items() if v not in (None, "", [])}}
        merged["customer"] = {**out["customer"], **(data.get("customer") or {})}
        return RoleplayIn.model_validate(_clamp(merged)).model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("roleplay draft failed, using basic draft: %s", exc)
        events.fallback("builder.draft", exc)
        return out


def _clamp(d: dict) -> dict:
    """Keep a model draft inside the limits a person's own edits must meet."""
    c = d["customer"]
    goals = [
        {**g, "weight": max(1, min(5, int(g.get("weight") or 1)))}
        for g in d.get("goals", [])[:6]
        if isinstance(g, dict) and g.get("name")
    ]
    return {
        **d,
        "title": str(d.get("title", ""))[:80],
        "minutes": max(2, min(20, int(d.get("minutes") or coach.DEFAULT_CALL_MINUTES))),
        "goals": goals or [dict(g) for g in DEFAULT_GOALS],
        "customer": {**c, "hidden_objections": list(c.get("hidden_objections", []))[:15]},
    }


# Personas


def personas(user: Principal) -> list[dict]:
    built_in = [{**p, "built_in": True} for p in _load_config("personas.json")]
    mine = [{**p, "built_in": False} for p in store.list_personas(user.user_id)]
    return built_in + mine


def save_persona(body: PersonaIn, user: Principal) -> dict:
    cap = _int_env("MAX_PERSONAS_PER_USER", DEFAULT_MAX_PERSONAS_PER_USER)
    if store.count_personas(user.user_id) >= cap:
        raise LimitReached(f"You can keep up to {cap} personas. Delete one to make room.")
    pid = store.save_persona(user.user_id, body.model_dump())
    return {**body.model_dump(), "id": pid, "built_in": False}


def check_draft_allowed() -> None:
    """Drafts use the model, so they stop with everything else at the daily spend cap."""
    limits.check_spend()

"""Live coach assist: the agent's next move on a practice call, shown while the customer speaks.

The coach here knows only what the agent may know: the public brief, the conversation so far, the
rubric and the product facts. It never gets the customer's hidden objections or private persona,
so a hint can't give away a concern the customer hasn't raised. Without a model, past the daily
spend cap, or if the model's reply is unusable, a scripted move for the stage of the call is used.
"""

from __future__ import annotations

import logging

from app import coach, events, limits, offline, schemas, usage
from app.llm import get_llm

logger = logging.getLogger(__name__)

STAGES = ("opening", "discovery", "value", "objection", "close")
MAX_TOKENS = 2000  # thinking and the JSON reply share this budget
LIMITS = {"move": 200, "avoid": 160, "line": 300}

_SCRIPTED = {
    "opening": {
        "move": "Greet {name}, say who you are, and ask if now is a good time.",
        "avoid": "Pitching the product in your first line.",
        "line": "Hi {name}, thanks for picking up. Is now an okay time for a few minutes?",
    },
    "discovery": {
        "move": "Ask an open question about how {name} works today, then listen.",
        "avoid": "Listing features before you know the problem.",
        "line": "Could you walk me through how you handle this today?",
    },
    "value": {
        "move": "Repeat back what {name} told you, then link one benefit to it.",
        "avoid": "Claims that aren't in the product facts.",
        "line": "So if I heard you right, that takes up a lot of your time. Can I show you one way to cut that down?",
    },
    "objection": {
        "move": "Acknowledge the concern, ask what's behind it, and answer honestly.",
        "avoid": "Arguing, or promising what you can't confirm.",
        "line": "That's fair. What worries you most about it?",
    },
    "close": {
        "move": "Suggest one small, clear next step and ask if it works for {name}.",
        "avoid": "Pushing for a decision today.",
        "line": "Would it help if we set up a short follow-up to try it with your own numbers?",
    },
}


def _agent_turns(session: dict) -> list[str]:
    return [t["agent_text"] for t in session["turns"] if t.get("agent_text")]


def _stage(agent_turns: list[str]) -> str:
    """Rough stage of the call from the agent's replies so far (offline only)."""
    n = len(agent_turns)
    if n == 0:
        return "opening"
    asked = any(offline.signals(t)["question"] for t in agent_turns)
    if n <= 2 or not asked:
        return "discovery"
    if n <= 4:
        return "value"
    return "objection" if n <= 6 else "close"


def _scripted(session: dict, scenario: dict) -> dict:
    stage = _stage(_agent_turns(session))
    name = scenario["customer"]["name"]
    return {"stage": stage, **{k: v.format(name=name) for k, v in _SCRIPTED[stage].items()}}


def _system(scenario: dict) -> str:
    public = coach.public_scenario(scenario)
    goals = "\n".join(f"- {g}" for g in public["goals"]) or "- none set"
    return f"""You are a sales coach whispering to a trainee agent during a live practice call.
The customer has just spoken. Tell the agent the best next move. Reply with JSON only.

What the agent knows about the call:
Customer: {public["customer_name"]} {public["customer_role"]}
Brief: {public["public_brief"]}
Goals for this call:
{goals}

Good calls show these behaviours:
{coach._rubric_lines(coach.load_rubric())}

Product facts (the only truth about the product):
{coach.load_product()}

Rules:
- React to what the customer actually said last. Do not guess concerns they have not raised.
- Any product claim in your suggested line must be supported by the product facts above.
- "stage" is where the call is now: one of {", ".join(STAGES)}.
- "move": what to do next, at most 20 words.
- "avoid": the most likely mistake right now, at most 12 words, or empty.
- "line": one natural sentence or two the agent could say, at most 30 words.

Reply with exactly this JSON shape:
{{"stage": "...", "move": "...", "avoid": "...", "line": "..."}}"""


def _clean(data: dict, fallback_stage: str) -> dict:
    stage = str(data.get("stage", "")).lower()
    out = {"stage": stage if stage in STAGES else fallback_stage}
    for key, limit in LIMITS.items():
        out[key] = str(data.get(key, "")).strip()[:limit]
    return out


def _from_model(llm, session: dict, scenario: dict, scripted: dict) -> dict:
    user = f"Conversation so far:\n{coach._transcript(session['turns'])}\n\nJSON:"
    with usage.kind("assist"):
        data = coach.ask_model(
            llm,
            system=_system(scenario),
            user=user,
            max_tokens=MAX_TOKENS,
            schema=schemas.assist_schema(list(STAGES)),
        )
    move = _clean(data, scripted["stage"])
    if not move["move"]:
        raise ValueError("empty move")
    return move


def next_move(session: dict, scenario: dict) -> dict:
    """The agent's next move: stage, what to do, what to avoid, and a line they could say."""
    scripted = _scripted(session, scenario)
    llm = get_llm()
    if llm is None:
        return {**scripted, "fallback": False}
    try:
        limits.check_spend()
    except limits.LimitReached:
        return {**scripted, "fallback": True}
    try:
        return {**_from_model(llm, session, scenario, scripted), "fallback": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("assist model call failed, using a scripted move: %s", exc)
        events.fallback("coach.assist", exc)
        return {**scripted, "fallback": True}

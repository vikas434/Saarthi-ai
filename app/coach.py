"""The AI customer, the live coach and the SQS scorecard."""

from __future__ import annotations

import json
import logging
import re

from app import offline, store
from app.config import CONFIG_DIR, MAX_AGENT_TURNS
from app.llm import get_llm, parse_json

logger = logging.getLogger(__name__)
PROMPT_VERSION = "sqs-coach@1"


def load_rubric() -> dict:
    return json.loads((CONFIG_DIR / "rubric.json").read_text(encoding="utf-8"))


def load_product() -> str:
    return store.get_kv("product") or (CONFIG_DIR / "product.md").read_text(encoding="utf-8")


def load_scenarios() -> list[dict]:
    built_in = json.loads((CONFIG_DIR / "scenarios.json").read_text(encoding="utf-8"))
    return built_in + store.custom_scenarios()


def get_scenario(scenario_id: str) -> dict | None:
    return next((s for s in load_scenarios() if s["id"] == scenario_id), None)


def public_scenario(s: dict) -> dict:
    """What the sales agent may see: never the hidden objections."""
    return {
        "id": s["id"],
        "title": s["title"],
        "difficulty": s.get("difficulty", "Medium"),
        "public_brief": s["public_brief"],
        "customer_name": s["customer"]["name"],
    }


def _rubric_lines(rubric: dict) -> str:
    return "\n".join(f"- {b['id']}: {b['name']}. {b['description']}" for b in rubric["behaviors"])


def _transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        if t.get("agent_text"):
            lines.append(f"Agent: {t['agent_text']}")
        lines.append(f"Customer: {t['customer_text']}")
    return "\n".join(lines)


def _turn_system(scenario: dict, rubric: dict, product: str) -> str:
    c = scenario["customer"]
    return f"""You do two jobs in a sales practice session and reply with JSON only.

JOB 1 - Play the customer. Stay in character. Never mention that you are an AI or a coach.
Name: {c["name"]}
Who you are: {c["persona"]}
Mood at the start: {c["mood"]}
Your situation: {c["situation"]}
Concerns you do NOT volunteer; raise one only when the conversation naturally reaches it:
{json.dumps(c.get("hidden_objections", []))}
You warm up and move toward yes when: {c.get("wins_if", "")}
You cool down and end the call when: {c.get("walks_away_if", "")}
Speak like a real person on a call: one to three short sentences. React to what the agent
actually said. If the agent states something about the product, treat it as true in character,
even if it is wrong (the coach handles accuracy). Set "done" to true only when the call has
reached a natural end: you agreed to a next step, or you are leaving.

JOB 2 - Be the silent coach. Judge only the agent's LATEST message against this rubric:
{_rubric_lines(rubric)}
Pick the one behaviour that message shows most clearly (well or badly).
If the agent stated a product fact that is not supported by the product facts below, or made a
promise the facts forbid, the behaviour is "accuracy" and the verdict is "improve".

Product facts (the only truth about the product):
{product}

Reply with exactly this JSON shape:
{{"customer": "what the customer says next",
 "done": false,
 "coach": {{"verdict": "good" | "mixed" | "improve",
            "behavior": "<rubric id>",
            "note": "one sentence on what the agent just did, quoting a few of their words",
            "try_instead": "one sentence the agent could have said, or empty when verdict is good"}}}}"""


def _clean_coach(coach: dict, rubric: dict) -> dict:
    ids = {b["id"] for b in rubric["behaviors"]}
    verdict = str(coach.get("verdict", "mixed")).lower()
    return {
        "verdict": verdict if verdict in {"good", "mixed", "improve"} else "mixed",
        "behavior": coach.get("behavior") if coach.get("behavior") in ids else "clarity",
        "note": str(coach.get("note", ""))[:400],
        "try_instead": str(coach.get("try_instead", ""))[:400],
    }


def mode() -> str:
    llm = get_llm()
    return llm.name if llm else "offline"


def next_turn(session: dict, agent_text: str) -> dict:
    """Customer reply plus a coaching note for the agent's message."""
    scenario = get_scenario(session["scenario_id"])
    rubric = load_rubric()
    agent_turns = [t["agent_text"] for t in session["turns"] if t.get("agent_text")] + [agent_text]
    llm = get_llm()
    result = None
    if llm is not None:
        user = (
            f"Conversation so far:\n{_transcript(session['turns'])}\n\n"
            f"Agent's latest message:\n{agent_text}\n\nJSON:"
        )
        try:
            data = parse_json(
                llm.complete(
                    system=_turn_system(scenario, rubric, load_product()), user=user, max_tokens=500
                )
            )
            result = {
                "customer": str(data["customer"]).strip(),
                "done": bool(data.get("done")),
                "coach": _clean_coach(data.get("coach") or {}, rubric),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("turn model call failed, using offline reply: %s", exc)
    if result is None:
        result = offline.turn(scenario, agent_turns)
        result["coach"] = _clean_coach(result["coach"], rubric)
    if len(agent_turns) >= MAX_AGENT_TURNS:
        result["done"] = True
    return result


def _report_system(rubric: dict, product: str, scenario: dict) -> str:
    return f"""You are a sales coach scoring a practice call for behavioural quality. JSON only.

Rubric (score each behaviour 1 to 5; use null when the call gave no chance to show it):
{_rubric_lines(rubric)}
1 = harmful or absent when clearly needed, 3 = adequate, 5 = excellent and consistent.
Score what the agent did, not how the customer reacted. Be specific and fair: quote the agent.

Product facts (for the accuracy behaviour):
{product}

The customer's hidden concerns in this scenario (did the agent uncover and resolve them?):
{json.dumps(scenario["customer"].get("hidden_objections", []))}

Reply with exactly this JSON shape:
{{"behaviors": [{{"id": "<rubric id>", "score": 1-5 or null,
                 "evidence": "short quote from the agent, under 20 words",
                 "good": "what was good, one sentence, or empty",
                 "improve": "what to change, one sentence, or empty",
                 "say_instead": "a better line the agent could have said, or empty"}}],
 "strengths": ["2 or 3 short points"],
 "growth": ["2 or 3 short points"],
 "summary": "two sentences on how the call went",
 "next_drill": "one specific thing to practise in the next call"}}
Include every rubric id once, in rubric order. Escape double quotes inside strings."""


def weighted_sqs(rubric: dict, behaviors: list[dict]) -> float | None:
    weights = {b["id"]: float(b.get("weight", 1)) for b in rubric["behaviors"]}
    scored = [(weights.get(b["id"], 1.0), b["score"]) for b in behaviors if b.get("score")]
    total = sum(w for w, _ in scored)
    if not total:
        return None
    return round(100 * sum(w * s for w, s in scored) / (5 * total), 1)


def build_report(session: dict) -> dict:
    scenario = get_scenario(session["scenario_id"])
    rubric = load_rubric()
    agent_turns = [t["agent_text"] for t in session["turns"] if t.get("agent_text")]
    llm = get_llm()
    data, source = None, "offline"
    if llm is not None and agent_turns:
        try:
            data = parse_json(
                llm.complete(
                    system=_report_system(rubric, load_product(), scenario),
                    user=f"Transcript:\n{_transcript(session['turns'])}\n\nJSON:",
                    max_tokens=2500,
                )
            )
            source = llm.name
        except Exception as exc:  # noqa: BLE001
            logger.warning("report model call failed, using offline scoring: %s", exc)
    if data is None:
        data = offline.report(rubric, agent_turns)

    by_id = {b.get("id"): b for b in data.get("behaviors", []) if isinstance(b, dict)}
    behaviors = []
    for b in rubric["behaviors"]:
        got = by_id.get(b["id"], {})
        score = got.get("score")
        score = max(1, min(5, int(score))) if isinstance(score, int | float) else None
        behaviors.append(
            {
                "id": b["id"],
                "name": b["name"],
                "weight": b.get("weight", 1),
                "score": score,
                "evidence": str(got.get("evidence", "")),
                "good": str(got.get("good", "")),
                "improve": str(got.get("improve", "")),
                "say_instead": str(got.get("say_instead", "")),
            }
        )
    return {
        "sqs": weighted_sqs(rubric, behaviors),
        "behaviors": behaviors,
        "strengths": [str(x) for x in data.get("strengths", [])][:3],
        "growth": [str(x) for x in data.get("growth", [])][:3],
        "summary": str(data.get("summary", "")),
        "next_drill": str(data.get("next_drill", "")),
        "scored_by": source,
        "prompt_version": PROMPT_VERSION,
        "agent_turns": len(agent_turns),
    }


def draft_scenario(description: str) -> dict:
    """Turn one sentence into a practice scenario."""
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:40] or "custom"
    scenario = {
        "id": f"custom-{slug}",
        "title": description.strip()[:60],
        "difficulty": "Medium",
        "public_brief": description.strip(),
        "customer": {
            "name": "Alex",
            "persona": description.strip(),
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
    }
    llm = get_llm()
    if llm is not None:
        try:
            data = parse_json(
                llm.complete(
                    system=(
                        "Draft a sales practice scenario as JSON only, with keys: title, difficulty "
                        "(Easy|Medium|Hard), public_brief (what the agent is told, 1-2 sentences), "
                        "customer {name, persona, mood, situation, hidden_objections (3 strings), "
                        "wins_if, walks_away_if}, opening_line (the customer's first words). "
                        f"Base it on the product facts.\n\nProduct facts:\n{load_product()}"
                    ),
                    user=f"Customer to practise with: {description}\n\nJSON:",
                    max_tokens=700,
                )
            )
            for key in ("title", "difficulty", "public_brief", "opening_line"):
                if data.get(key):
                    scenario[key] = str(data[key])
            if isinstance(data.get("customer"), dict):
                scenario["customer"].update(data["customer"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("scenario draft failed, using basic draft: %s", exc)
    return scenario


def progress() -> dict:
    """Average score per behaviour across scored sessions, and the SQS trend."""
    reports = store.scored_reports()
    rubric = load_rubric()
    per: dict[str, list[int]] = {b["id"]: [] for b in rubric["behaviors"]}
    for r in reports:
        for b in r.get("behaviors", []):
            if b.get("score") and b["id"] in per:
                per[b["id"]].append(b["score"])
    return {
        "sessions": len(reports),
        "trend": [r.get("sqs") for r in reports if r.get("sqs") is not None],
        "behaviors": [
            {
                "id": b["id"],
                "name": b["name"],
                "average": round(sum(per[b["id"]]) / len(per[b["id"]]), 2)
                if per[b["id"]]
                else None,
            }
            for b in rubric["behaviors"]
        ],
    }

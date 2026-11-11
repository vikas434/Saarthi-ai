"""The AI customer, the live coach and the SQS scorecard."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app import offline, schemas, store
from app.config import CONFIG_DIR, MAX_AGENT_TURNS
from app.llm import LLM, ModelReplyError, get_llm, parse_json

logger = logging.getLogger(__name__)
PROMPT_VERSION = "saarthi@3"
PARSE_ATTEMPTS = 2  # one retry when the model's reply can't be used
TURN_MAX_TOKENS = 4000  # thinking and the JSON reply share this budget
REPORT_MAX_TOKENS = 12000
SURVEY_MAX_TOKENS = 3000
SCENARIO_MAX_TOKENS = 3000
REPORT_EFFORT = "medium"  # judging a whole call needs more care than one customer line
MARKER_TYPES = ("rubric", "survey", "checklist")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "item"


def load_markers() -> list[dict]:
    """Quality markers: the built-in ones plus any added in Setup.

    rubric: behaviours scored 1-5 by the coach, weighted into a percentage.
    survey: a question the customer answers in character after the call (tNPS, ProSat).
    checklist: yes / no / not-applicable items, some critical.
    """
    built_in = json.loads((CONFIG_DIR / "markers.json").read_text(encoding="utf-8"))
    custom = json.loads(store.get_kv("custom_markers") or "[]")
    return built_in + custom


def all_behaviors(markers: list[dict] | None = None) -> list[dict]:
    seen, out = set(), []
    for m in markers or load_markers():
        for b in m.get("behaviors", []) if m["type"] == "rubric" else []:
            if b["id"] not in seen:
                seen.add(b["id"])
                out.append(b)
    return out


def load_rubric() -> dict:
    """All behaviours the live coach may comment on."""
    return {"behaviors": all_behaviors()}


def add_marker(
    name: str, kind: str, lines: list[str], *, question: str = "", lo: int = 1, hi: int = 5
) -> dict:
    """Add a marker from Setup. Rubric lines are "Name - what good looks like"; checklist
    lines are items, with a leading ! marking a critical one."""
    if kind not in MARKER_TYPES:
        raise ValueError("type must be rubric, survey or checklist")
    marker: dict = {
        "id": f"custom-{_slug(name)}",
        "name": name.strip(),
        "type": kind,
        "description": "Added in Setup.",
        "custom": True,
    }
    clean = [x.strip() for x in lines if x.strip()]
    if kind == "rubric":
        if not clean:
            raise ValueError("a rubric needs at least one behaviour line")
        marker["behaviors"] = []
        for line in clean:
            title, _, desc = line.partition(" - ")
            marker["behaviors"].append(
                {
                    "id": f"{_slug(name)}-{_slug(title)}",
                    "name": title.strip(),
                    "weight": 1,
                    "description": desc.strip() or title.strip(),
                }
            )
    elif kind == "checklist":
        if not clean:
            raise ValueError("a checklist needs at least one item")
        marker["items"] = [
            {"id": _slug(x.lstrip("! ")), "text": x.lstrip("! "), "critical": x.startswith("!")}
            for x in clean
        ]
    else:
        if not question.strip() or hi <= lo:
            raise ValueError("a survey needs a question and a scale")
        marker.update(question=question.strip(), min=lo, max=hi, drivers=[])
    custom = [
        m for m in json.loads(store.get_kv("custom_markers") or "[]") if m["id"] != marker["id"]
    ]
    store.set_kv("custom_markers", json.dumps(custom + [marker]))
    return marker


def remove_marker(marker_id: str) -> bool:
    custom = json.loads(store.get_kv("custom_markers") or "[]")
    kept = [m for m in custom if m["id"] != marker_id]
    store.set_kv("custom_markers", json.dumps(kept))
    return len(kept) != len(custom)


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


def _ask(
    llm: LLM,
    *,
    system: str,
    user: str,
    max_tokens: int,
    schema: dict,
    effort: str | None = None,
) -> dict:
    """Call the model and parse its JSON, retrying once if the reply is unusable."""
    last: Exception | None = None
    for attempt in range(1, PARSE_ATTEMPTS + 1):
        try:
            return parse_json(
                llm.complete(
                    system=system, user=user, max_tokens=max_tokens, schema=schema, effort=effort
                )
            )
        except (ValueError, ModelReplyError) as exc:
            last = exc
            logger.warning("unusable model reply (attempt %d/%d): %s", attempt, PARSE_ATTEMPTS, exc)
    raise ModelReplyError(f"no usable reply after {PARSE_ATTEMPTS} attempts") from last


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
            data = _ask(
                llm,
                system=_turn_system(scenario, rubric, load_product()),
                user=user,
                max_tokens=TURN_MAX_TOKENS,
                schema=schemas.turn_schema([b["id"] for b in rubric["behaviors"]]),
            )
            result = {
                "customer": str(data["customer"]).strip(),
                "done": bool(data.get("done")),
                "coach": _clean_coach(data.get("coach") or {}, rubric),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("turn model call failed, using offline reply: %s", exc)
    fallback = llm is not None and result is None
    if result is None:
        result = offline.turn(scenario, agent_turns)
        result = {**result, "coach": _clean_coach(result["coach"], rubric)}
    return {
        **result,
        "done": result["done"] or len(agent_turns) >= MAX_AGENT_TURNS,
        "fallback": fallback,
        "coach": {**result["coach"], "fallback": fallback},
    }


def _checklist_items(markers: list[dict]) -> list[dict]:
    return [
        {**item, "key": f"{m['id']}.{item['id']}", "marker": m["name"]}
        for m in markers
        if m["type"] == "checklist"
        for item in m["items"]
    ]


def _report_system(behaviors: list[dict], items: list[dict], product: str, scenario: dict) -> str:
    checklist = "\n".join(f"- {i['key']}: {i['text']}" for i in items) or "(none)"
    return f"""You are a sales coach scoring a practice call for behavioural quality. JSON only.

Behaviours (score each 1 to 5; use null when the call gave no chance to show it):
{_rubric_lines({"behaviors": behaviors})}
1 = harmful or absent when clearly needed, 3 = adequate, 5 = excellent and consistent.
Score what the agent did, not how the customer reacted. Be specific and fair: quote the agent.
Accuracy rule: if the agent made any claim or promise the product facts do not support, or
anything the facts say never to promise, score accuracy 1 (or 2 if the agent corrected it
clearly during the call). The checklist item about promises is then "no".

Checklist items (answer "yes", "no", or "na" when the call gave no occasion for it):
{checklist}

Product facts (the only truth about the product; use them to judge claims and promises):
{product}

The customer's hidden concerns in this scenario (did the agent uncover and resolve them?):
{json.dumps(scenario["customer"].get("hidden_objections", []))}

Reply with exactly this JSON shape:
{{"behaviors": [{{"id": "<behaviour id>", "score": 1-5 or null,
                 "evidence": "short quote from the agent, under 20 words",
                 "good": "what was good, one sentence, or empty",
                 "improve": "what to change, one sentence, or empty",
                 "say_instead": "a better line the agent could have said, or empty"}}],
 "checklist": [{{"id": "<checklist item id>", "result": "yes" | "no" | "na",
                 "evidence": "short quote or reason, under 20 words"}}],
 "strengths": ["2 or 3 short points"],
 "growth": ["2 or 3 short points"],
 "summary": "two sentences on how the call went",
 "next_drill": "one specific thing to practise in the next call"}}
Include every behaviour id and every checklist item id once. Escape double quotes in strings."""


def _survey_system(scenario: dict, surveys: list[dict]) -> str:
    c = scenario["customer"]
    questions = "\n".join(
        f"- {m['id']}: {m['question']} Answer with a whole number from {m['min']} to {m['max']}."
        for m in surveys
    )
    return f"""The call is over. You are still {c["name"]}: {c["persona"]}
Your situation was: {c["situation"]}
Your private concerns were: {json.dumps(c.get("hidden_objections", []))}
You have been sent a short survey about the call you just had. Answer honestly as this customer
would, based only on how the agent treated you and what you learned. An agent who listened and
resolved your concerns earns a high score; one who pushed, ignored you or left concerns open
earns a low one. Do not be generous by default.

Survey questions:
{questions}

Reply with JSON only:
{{"answers": [{{"id": "<question id>", "score": <number>,
               "reason": "one sentence in your own voice as the customer"}}]}}"""


def _weighted_percent(behaviors: list[dict]) -> float | None:
    scored = [(float(b.get("weight", 1)), b["score"]) for b in behaviors if b.get("score")]
    total = sum(w for w, _ in scored)
    if not total:
        return None
    return round(100 * sum(w * s for w, s in scored) / (5 * total), 1)


def _coach_data(llm, session, scenario, behaviors, items, agent_turns) -> tuple[dict, str]:
    if llm is not None:
        try:
            data = _ask(
                llm,
                system=_report_system(behaviors, items, load_product(), scenario),
                user=f"Transcript:\n{_transcript(session['turns'])}\n\nJSON:",
                max_tokens=REPORT_MAX_TOKENS,
                effort=REPORT_EFFORT,
                schema=schemas.report_schema(
                    [b["id"] for b in behaviors], [i["key"] for i in items]
                ),
            )
            return data, llm.name
        except Exception as exc:  # noqa: BLE001
            logger.warning("report model call failed, using offline scoring: %s", exc)
    return offline.coach_report(behaviors, items, agent_turns), "offline"


def _survey_data(llm, session, scenario, surveys, agent_turns) -> tuple[list[dict], str]:
    if not surveys:
        return [], "none"
    if llm is not None:
        try:
            data = _ask(
                llm,
                system=_survey_system(scenario, surveys),
                user=f"The call:\n{_transcript(session['turns'])}\n\nJSON:",
                max_tokens=SURVEY_MAX_TOKENS,
                schema=schemas.survey_schema([m["id"] for m in surveys]),
            )
            return list(data.get("answers", [])), llm.name
        except Exception as exc:  # noqa: BLE001
            logger.warning("survey model call failed, using offline estimate: %s", exc)
    return offline.survey(surveys, agent_turns), "offline"


def build_report(session: dict) -> dict:
    """Score the call on every marker: coach scoring and the customer's survey run together."""
    scenario = get_scenario(session["scenario_id"])
    markers = load_markers()
    behaviors = all_behaviors(markers)
    items = _checklist_items(markers)
    surveys = [m for m in markers if m["type"] == "survey"]
    agent_turns = [t["agent_text"] for t in session["turns"] if t.get("agent_text")]
    llm = get_llm()
    with ThreadPoolExecutor(max_workers=2) as pool:
        coach_future = pool.submit(
            _coach_data, llm, session, scenario, behaviors, items, agent_turns
        )
        survey_future = pool.submit(_survey_data, llm, session, scenario, surveys, agent_turns)
        data, source = coach_future.result()
        answers, survey_source = survey_future.result()

    got_b = {b.get("id"): b for b in data.get("behaviors", []) if isinstance(b, dict)}
    got_c = {c.get("id"): c for c in data.get("checklist", []) if isinstance(c, dict)}
    got_s = {a.get("id"): a for a in answers if isinstance(a, dict)}

    def behavior_out(b: dict) -> dict:
        got = got_b.get(b["id"], {})
        score = got.get("score")
        score = max(1, min(5, int(score))) if isinstance(score, int | float) else None
        return {
            "id": b["id"],
            "name": b["name"],
            "weight": b.get("weight", 1),
            "score": score,
            "evidence": str(got.get("evidence", "")),
            "good": str(got.get("good", "")),
            "improve": str(got.get("improve", "")),
            "say_instead": str(got.get("say_instead", "")),
        }

    scored_b = {b["id"]: behavior_out(b) for b in behaviors}
    out = []
    for m in markers:
        base = {
            "id": m["id"],
            "name": m["name"],
            "type": m["type"],
            "description": m.get("description", ""),
        }
        if m["type"] == "rubric":
            rows = [scored_b[b["id"]] for b in m["behaviors"]]
            out.append({**base, "percent": _weighted_percent(rows), "behaviors": rows})
        elif m["type"] == "survey":
            got = got_s.get(m["id"], {})
            score = got.get("score")
            if isinstance(score, int | float):
                score = max(m["min"], min(m["max"], round(score)))
            else:
                score = None
            drivers = [
                {"id": d, "name": scored_b[d]["name"], "score": scored_b[d]["score"]}
                for d in m.get("drivers", [])
                if d in scored_b
            ]
            out.append(
                {
                    **base,
                    "score": score,
                    "min": m["min"],
                    "max": m["max"],
                    "question": m["question"],
                    "reason": str(got.get("reason", "")),
                    "drivers": drivers,
                    "answered_by": survey_source,
                }
            )
        else:
            rows = []
            for item in m["items"]:
                got = got_c.get(f"{m['id']}.{item['id']}", {})
                result = str(got.get("result", "na")).lower()
                rows.append(
                    {
                        "id": item["id"],
                        "text": item["text"],
                        "critical": bool(item.get("critical")),
                        "result": result if result in {"yes", "no", "na"} else "na",
                        "evidence": str(got.get("evidence", "")),
                    }
                )
            applicable = [r for r in rows if r["result"] != "na"]
            passed = sum(1 for r in applicable if r["result"] == "yes")
            out.append(
                {
                    **base,
                    "items": rows,
                    "passed": passed,
                    "applicable": len(applicable),
                    "percent": round(100 * passed / len(applicable), 1) if applicable else None,
                    "critical_missed": [
                        r["text"] for r in rows if r["critical"] and r["result"] == "no"
                    ],
                }
            )
    headline = next((m for m in out if m["type"] == "rubric"), None)
    return {
        "sqs": headline["percent"] if headline else None,
        "headline": headline["name"] if headline else "",
        "markers": out,
        "strengths": [str(x) for x in data.get("strengths", [])][:3],
        "growth": [str(x) for x in data.get("growth", [])][:3],
        "summary": str(data.get("summary", "")),
        "next_drill": str(data.get("next_drill", "")),
        "scored_by": source,
        "fallback": llm is not None and "offline" in (source, survey_source),
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
            data = _ask(
                llm,
                system=(
                    "Draft a sales practice scenario as JSON only, with keys: title, difficulty "
                    "(Easy|Medium|Hard), public_brief (what the agent is told, 1-2 sentences), "
                    "customer {name, persona, mood, situation, hidden_objections (3 strings), "
                    "wins_if, walks_away_if}, opening_line (the customer's first words). "
                    f"Base it on the product facts.\n\nProduct facts:\n{load_product()}"
                ),
                user=f"Customer to practise with: {description}\n\nJSON:",
                max_tokens=SCENARIO_MAX_TOKENS,
                schema=schemas.scenario_schema(),
            )
            for key in ("title", "difficulty", "public_brief", "opening_line"):
                if data.get(key):
                    scenario[key] = str(data[key])
            if isinstance(data.get("customer"), dict):
                scenario["customer"].update(data["customer"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("scenario draft failed, using basic draft: %s", exc)
    return scenario


def progress(user_id: str | None = None) -> dict:
    """Trend per marker and average per behaviour across scored calls (one user's, or all)."""
    reports = store.scored_reports(user_id)
    markers = load_markers()
    trends: dict[str, list] = {m["id"]: [] for m in markers}
    per: dict[str, list[int]] = {}
    for r in reports:
        for m in r.get("markers", []):
            value = m.get("score") if m["type"] == "survey" else m.get("percent")
            if value is not None and m["id"] in trends:
                trends[m["id"]].append(value)
            for b in m.get("behaviors", []):
                if b.get("score"):
                    per.setdefault(b["id"], []).append(b["score"])
    return {
        "sessions": len(reports),
        "markers": [
            {
                "id": m["id"],
                "name": m["name"],
                "type": m["type"],
                "max": m.get("max"),
                "trend": trends[m["id"]],
                "average": round(sum(trends[m["id"]]) / len(trends[m["id"]]), 1)
                if trends[m["id"]]
                else None,
            }
            for m in markers
        ],
        "behaviors": [
            {
                "id": b["id"],
                "name": b["name"],
                "average": round(sum(per[b["id"]]) / len(per[b["id"]]), 2)
                if per.get(b["id"])
                else None,
            }
            for b in all_behaviors(markers)
        ],
    }

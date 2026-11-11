"""Offline demo mode: a scripted customer and rule-of-thumb coaching, used when no model key
is set. Good enough to show the flow; real coaching needs a model."""

from __future__ import annotations

import re

_EMPATHY = re.compile(
    r"\b(sorry|understand|i hear|that sounds|frustrat|appreciate|makes sense)\b", re.IGNORECASE
)
_REFLECT = re.compile(
    r"\b(so you|sounds like|you mentioned|you said|if i understand)\b", re.IGNORECASE
)
_NEXT = re.compile(
    r"\b(trial|next step|shall i|can i send|schedule|set up|follow up|sign you up)\b", re.IGNORECASE
)
_PUSH = re.compile(r"\b(today only|right now|must|last chance|guarantee)\b", re.IGNORECASE)
_VALUE = re.compile(
    r"\b(save|so that|which means|for you|your (sunday|accountant|cafe|invoices))\b", re.IGNORECASE
)
_GREET = re.compile(r"\b(hi|hello|good (morning|afternoon|evening)|thanks for)\b", re.IGNORECASE)


def signals(text: str) -> dict[str, bool]:
    return {
        "question": "?" in text,
        "empathy": bool(_EMPATHY.search(text)),
        "reflect": bool(_REFLECT.search(text)),
        "next_step": bool(_NEXT.search(text)),
        "pushy": bool(_PUSH.search(text)),
        "value": bool(_VALUE.search(text)),
        "long": len(text.split()) > 70,
        "greeting": bool(_GREET.search(text)),
    }


def turn(scenario: dict, agent_turns: list[str]) -> dict:
    s = signals(agent_turns[-1])
    objections = scenario["customer"].get("hidden_objections", [])
    n = len(agent_turns)
    worry = objections[(n - 1) % len(objections)].lower() if objections else ""
    if s["pushy"]:
        customer = "I don't like being rushed. I'll think about it."
        coach = (
            "improve",
            "next_step",
            "That sounded like pressure.",
            "Offer the free trial and let the customer choose the pace.",
        )
    elif s["empathy"] or s["reflect"]:
        customer = "Yes, exactly. " + (
            f"Honestly, my worry is this: {worry}." if worry else "Go on."
        )
        coach = (
            "good",
            "empathy" if s["empathy"] else "listening",
            "You acknowledged the customer before moving on.",
            "",
        )
    elif s["question"]:
        customer = (
            "Well, it's a small business and I do most of it myself. It takes a lot of my time."
        )
        coach = ("good", "discovery", "Good open question before pitching.", "")
    elif s["long"]:
        customer = "That's a lot of information. What does it mean for me?"
        coach = (
            "improve",
            "clarity",
            "Long answer without checking in.",
            "Give one benefit tied to their need, then ask a question.",
        )
    else:
        customer = "Hmm. " + (f"But here's my concern: {worry}." if worry else "I'm not sure.")
        coach = (
            "mixed",
            "discovery",
            "You told, but didn't ask.",
            "Ask what matters most to them before explaining more.",
        )
    done = n >= 8 or (s["next_step"] and n >= 4)
    if done and not s["pushy"]:
        customer = "Okay, that works. Send me the details."
    return {
        "customer": customer,
        "done": done,
        "coach": {
            "verdict": coach[0],
            "behavior": coach[1],
            "note": coach[2],
            "try_instead": coach[3],
        },
    }


def behavior_scores(agent_turns: list[str]) -> dict[str, int | None]:
    sig = [signals(t) for t in agent_turns]
    n = max(len(sig), 1)

    def rate(key: str) -> float:
        return sum(1 for s in sig if s[key]) / n

    def scale(x: float) -> int:
        return max(1, min(5, round(1 + 4 * x)))

    pushy = any(s["pushy"] for s in sig)
    return {
        "opening": 4 if sig and sig[0]["greeting"] else 2,
        "discovery": scale(min(1.0, rate("question") * 1.6)),
        "listening": scale(min(1.0, rate("reflect") * 2.5)),
        "empathy": scale(min(1.0, rate("empathy") * 2.5)),
        "accuracy": 1 if pushy else None,
        "value": scale(min(1.0, rate("value") * 2.5)),
        "objections": scale(min(1.0, (rate("empathy") + rate("reflect")) * 1.5)),
        "next_step": 1 if pushy else (4 if any(s["next_step"] for s in sig) else 2),
        "clarity": scale(1 - rate("long")),
    }


def coach_report(
    behaviors: list[dict], checklist_items: list[dict], agent_turns: list[str]
) -> dict:
    scores = behavior_scores(agent_turns)
    sig = [signals(t) for t in agent_turns]
    any_sig = {k: any(s[k] for s in sig) for k in (sig[0] if sig else signals(""))}
    out_b = []
    for b in behaviors:
        score = scores.get(b["id"], 3)
        out_b.append(
            {
                "id": b["id"],
                "score": score,
                "evidence": "",
                "good": "Shown in several replies." if score and score >= 4 else "",
                "improve": f"Practise this: {b['description']}" if score and score < 4 else "",
                "say_instead": "",
            }
        )
    out_c = []
    for item in checklist_items:
        text = item["text"].lower()
        if "greet" in text:
            result = "yes" if sig and sig[0]["greeting"] else "no"
        elif "question" in text or "needs" in text:
            result = "yes" if any_sig.get("question") else "no"
        elif "pressure" in text or "promise" in text:
            result = "no" if any_sig.get("pushy") else "yes"
        elif "next step" in text:
            result = "yes" if any_sig.get("next_step") else "no"
        elif "empath" in text or "acknowledg" in text:
            result = "yes" if any_sig.get("empathy") else "no"
        else:
            result = "na"
        out_c.append({"id": item["key"], "result": result, "evidence": ""})
    return {
        "behaviors": out_b,
        "checklist": out_c,
        "strengths": ["Stayed in the conversation to the end"],
        "growth": ["Connect a model key for detailed, quote-level coaching"],
        "summary": "Offline demo scoring from simple signals (questions, empathy words, next steps).",
        "next_drill": "Open with two discovery questions before any product detail.",
    }


def survey(surveys: list[dict], agent_turns: list[str]) -> list[dict]:
    scores = behavior_scores(agent_turns)
    out = []
    for m in surveys:
        vals = [scores[d] for d in m.get("drivers", []) if scores.get(d)]
        avg = sum(vals) / len(vals) if vals else 3.0
        lo, hi = m["min"], m["max"]
        score = round(lo + (hi - lo) * (avg - 1) / 4)
        out.append(
            {
                "id": m["id"],
                "score": score,
                "reason": "Offline estimate from the behaviours that drive this marker.",
            }
        )
    return out

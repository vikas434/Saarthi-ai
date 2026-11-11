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


def signals(text: str) -> dict[str, bool]:
    words = len(text.split())
    return {
        "question": "?" in text,
        "empathy": bool(_EMPATHY.search(text)),
        "reflect": bool(_REFLECT.search(text)),
        "next_step": bool(_NEXT.search(text)),
        "pushy": bool(_PUSH.search(text)),
        "value": bool(_VALUE.search(text)),
        "long": words > 70,
        "greeting": bool(
            re.search(
                r"\b(hi|hello|good (morning|afternoon|evening)|thanks for)\b", text, re.IGNORECASE
            )
        ),
    }


def turn(scenario: dict, agent_turns: list[str]) -> dict:
    text = agent_turns[-1]
    s = signals(text)
    objections = scenario["customer"].get("hidden_objections", [])
    n = len(agent_turns)
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
            f"Honestly, my worry is this: {objections[(n - 1) % len(objections)].lower()}."
            if objections
            else "Go on."
        )
        coach = (
            "good",
            "empathy" if s["empathy"] else "listening",
            "You acknowledged the customer before moving on.",
            "",
        )
    elif s["question"]:
        customer = scenario["customer"].get("situation", "Well, it's a small business.")
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
        customer = "Hmm. " + (
            f"But {objections[(n - 1) % len(objections)].lower()}."
            if objections
            else "I'm not sure."
        )
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


def report(rubric: dict, agent_turns: list[str]) -> dict:
    sig = [signals(t) for t in agent_turns]
    n = max(len(sig), 1)

    def rate(key: str) -> float:
        return sum(1 for s in sig if s[key]) / n

    def scale(x: float) -> int:
        return max(1, min(5, round(1 + 4 * x)))

    pushy = any(s["pushy"] for s in sig)
    scores = {
        "opening": 4 if sig and sig[0]["greeting"] else 2,
        "discovery": scale(min(1.0, rate("question") * 1.6)),
        "listening": scale(min(1.0, rate("reflect") * 2.5)),
        "empathy": scale(min(1.0, rate("empathy") * 2.5)),
        "accuracy": None,
        "value": scale(min(1.0, rate("value") * 2.5)),
        "objections": scale(min(1.0, (rate("empathy") + rate("reflect")) * 1.5)),
        "next_step": 1 if pushy else (4 if any(s["next_step"] for s in sig) else 2),
        "clarity": scale(1 - rate("long")),
    }
    behaviors = []
    for b in rubric["behaviors"]:
        score = scores.get(b["id"], 3)
        behaviors.append(
            {
                "id": b["id"],
                "score": score,
                "evidence": "",
                "good": "" if score is None or score < 4 else "Shown in several replies.",
                "improve": ""
                if score is None or score >= 4
                else f"Practise this: {b['description']}",
                "say_instead": "",
            }
        )
    return {
        "behaviors": behaviors,
        "strengths": ["Stayed in the conversation to the end"],
        "growth": ["Connect a model key for detailed, quote-level coaching"],
        "summary": "Offline demo scoring from simple signals (questions, empathy words, next steps).",
        "next_drill": "Open with two discovery questions before any product detail.",
    }

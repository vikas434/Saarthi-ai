"""Tutor mode: a short lesson on the product facts before a roleplay, then three check questions.

The tutor teaches only from the product facts and the roleplay's public brief, never the hidden
objections. Answer keys stay on the server (the session's plan) until a question is answered.
Without a model key, the lesson and the grading come from the product facts text itself.
"""

from __future__ import annotations

import logging
import re

from app import coach, schemas, usage
from app.llm import get_llm

logger = logging.getLogger(__name__)

QUESTIONS = 3
READY_SCORE = 2  # answers right out of QUESTIONS to be "ready"
LESSON_MAX_TOKENS = 3000
GRADE_MAX_TOKENS = 1200
MAX_POINTS = 5
OFFLINE_PASS_RATIO = 0.5  # share of the answer key's key words an offline answer must contain
STOP_WORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "your",
        "you",
        "are",
        "can",
        "not",
        "but",
        "its",
        "per",
        "our",
        "has",
        "have",
        "was",
        "all",
        "any",
        "only",
        "into",
        "about",
        "every",
        "their",
        "them",
        "they",
        "what",
        "when",
        "will",
    ]
)


def _facts(product: str) -> list[tuple[str, str]]:
    """(heading, fact) pairs from the product facts, in order.

    Markdown bullets under "## " headings when the admin wrote them that way; otherwise every
    sentence is a fact under one heading, so facts pasted as plain text still teach.
    """
    heading, out = "", []
    for line in product.splitlines():
        line = line.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.startswith(("- ", "* ")):
            out.append((heading or "Product facts", line[2:].strip()))
    if out:
        return out
    plain = " ".join(line for line in product.splitlines() if not line.startswith("#"))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", plain) if len(s.strip()) > 3]
    return [("Product facts", s) for s in sentences]


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9,.\-]*", text.lower())
    return {w.strip(",.") for w in words if w.strip(",.") not in STOP_WORDS and len(w) >= 3}


def _topic(bullet: str) -> str:
    head = bullet.split(":", 1)[0]
    if ":" in bullet and len(head) <= 40:
        return head
    return " ".join(bullet.split()[:5]).rstrip(".,") + "…"


def offline_lesson(scenario: dict, product: str) -> dict:
    facts = _facts(product)
    sections: dict[str, list[str]] = {}
    for heading, bullet in facts:
        sections.setdefault(heading, []).append(bullet)
    points = [{"title": h, "explain": " ".join(b)} for h, b in sections.items()][:MAX_POINTS]
    if len(points) < QUESTIONS:  # few headings: teach fact by fact instead
        points = [{"title": _topic(b).rstrip("…"), "explain": b} for _, b in facts][:MAX_POINTS]
    focus = _keywords(f"{scenario['title']} {scenario['public_brief']}")
    ranked = sorted(
        enumerate(facts),
        key=lambda item: (
            -len(_keywords(item[1][1]) & focus),
            -bool(re.search(r"\d", item[1][1])),
            item[0],
        ),
    )
    questions = [
        {"question": f"What should you tell the customer about {_topic(b)}?", "answer": b}
        for _, (_, b) in ranked[:QUESTIONS]
    ]
    name = scenario["customer"]["name"]
    return {
        "intro": f"Before you speak with {name}, here are the product facts that matter.",
        "points": points,
        "questions": questions,
    }


def _lesson_system(scenario: dict, product: str) -> str:
    c = scenario["customer"]
    return f"""You are a product tutor preparing a sales agent for a practice call. JSON only.
Teach only what the product facts below say; never add product details of your own.

The call: {scenario["title"]}. {scenario["public_brief"]}
The customer: {c["name"]}{", " + c["role"] if c.get("role") else ""}.

Product facts:
{product}

Reply with: {{"intro": "one friendly sentence",
 "points": [3 to {MAX_POINTS} of {{"title": "2-4 words", "explain": "1-2 sentences"}}],
 "questions": [exactly {QUESTIONS} of {{"question": "a question the agent should be able to answer
 on this call", "answer": "the answer, from the facts"}}]}}
Pick the facts that matter most for this call."""


def lesson(scenario: dict) -> dict:
    """The plan for one tutor session: lesson, questions with answer keys, empty answers."""
    product = coach.load_product()
    base = offline_lesson(scenario, product)
    data, source = base, "offline"
    llm = get_llm()
    if llm is not None:
        try:
            with usage.kind("tutor"):
                got = coach.ask_model(
                    llm,
                    system=_lesson_system(scenario, product),
                    user="JSON:",
                    max_tokens=LESSON_MAX_TOKENS,
                    schema=schemas.tutor_lesson_schema(),
                )
            data, source = _clean_lesson(got, base), llm.name
        except Exception as exc:  # noqa: BLE001
            logger.warning("tutor lesson failed, using the facts as written: %s", exc)
    return {**data, "answers": [None] * QUESTIONS, "source": source}


def _clean_lesson(got: dict, base: dict) -> dict:
    points = [
        {"title": str(p.get("title", ""))[:60], "explain": str(p.get("explain", ""))[:400]}
        for p in got.get("points", [])
        if isinstance(p, dict) and p.get("title") and p.get("explain")
    ][:MAX_POINTS]
    questions = [
        {"question": str(q["question"])[:300], "answer": str(q["answer"])[:400]}
        for q in got.get("questions", [])
        if isinstance(q, dict) and q.get("question") and q.get("answer")
    ][:QUESTIONS]
    questions += base["questions"][len(questions) : QUESTIONS]
    return {
        "intro": str(got.get("intro") or base["intro"])[:300],
        "points": points or base["points"],
        "questions": questions,
    }


def public(sid: str, plan: dict) -> dict:
    """What the learner sees: never the answer keys of unanswered questions."""
    return {
        "id": sid,
        "intro": plan["intro"],
        "points": plan["points"],
        "questions": [q["question"] for q in plan["questions"]],
        "answers": plan["answers"],
    }


def _offline_grade(question: dict, text: str) -> dict:
    key = _keywords(question["answer"])
    hit = len(key & _keywords(text)) / len(key) if key else 0.0
    correct = hit >= OFFLINE_PASS_RATIO
    return {
        "correct": correct,
        "feedback": "That covers the key facts."
        if correct
        else "Not quite. Check the facts below.",
        "ideal": question["answer"],
    }


GRADE_SYSTEM = """You grade a sales agent's answer to a product quiz question. JSON only.
Correct means the answer states the key facts of the answer key accurately; wording can differ,
but a wrong number, price or promise makes it incorrect. Judge only against the answer key and
the product facts.
Reply with: {"correct": true or false, "feedback": "one encouraging sentence on what was right or
missing", "ideal": "the model answer in one or two sentences"}

Product facts:
"""


def grade(plan: dict, index: int, text: str) -> dict:
    question = plan["questions"][index]
    llm = get_llm()
    if llm is not None:
        try:
            with usage.kind("tutor"):
                got = coach.ask_model(
                    llm,
                    system=GRADE_SYSTEM + coach.load_product(),
                    user=(
                        f"Question: {question['question']}\nAnswer key: {question['answer']}\n"
                        f"Agent's answer: {text}\n\nJSON:"
                    ),
                    max_tokens=GRADE_MAX_TOKENS,
                    schema=schemas.tutor_grade_schema(),
                )
            return {
                "correct": bool(got.get("correct")),
                "feedback": str(got.get("feedback", ""))[:400],
                "ideal": str(got.get("ideal") or question["answer"])[:400],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("tutor grading failed, grading by key words: %s", exc)
    return _offline_grade(question, text)


def with_answer(plan: dict, index: int, text: str, result: dict) -> dict:
    """A new plan with this answer recorded."""
    answers = list(plan["answers"])
    answers[index] = {"text": text, **result}
    return {**plan, "answers": answers}


def finish(plan: dict) -> dict:
    score = sum(1 for a in plan["answers"] if a and a["correct"])
    ready = score >= READY_SCORE
    return {
        "type": "tutor",
        "score": score,
        "total": QUESTIONS,
        "ready": ready,
        "message": "You know the facts this call needs. Time to practise."
        if ready
        else "Read the facts again before you practise; the customer will ask about them.",
        "answers": [
            {
                "question": q["question"],
                **(a or {"text": "", "correct": False, "ideal": q["answer"]}),
            }
            for q, a in zip(plan["questions"], plan["answers"], strict=True)
        ],
        "scored_by": plan.get("source", "offline"),
    }

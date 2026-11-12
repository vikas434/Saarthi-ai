"""JSON schemas for model replies (structured outputs). Each one matches a prompt in coach.py.

Structured outputs do not support numeric bounds, so scores are clamped after parsing.
"""

from __future__ import annotations


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def turn_schema(behavior_ids: list[str]) -> dict:
    """The customer's next line plus one coach note on the agent's latest message."""
    coach = _obj(
        {
            "verdict": {"type": "string", "enum": ["good", "mixed", "improve"]},
            "behavior": {"type": "string", "enum": list(behavior_ids)},
            "note": _STR,
            "try_instead": _STR,
        }
    )
    return _obj({"customer": _STR, "done": {"type": "boolean"}, "coach": coach})


def report_schema(behavior_ids: list[str], checklist_keys: list[str]) -> dict:
    """The coach's scorecard: every behaviour and every checklist item, plus a summary."""
    behavior = _obj(
        {
            "id": {"type": "string", "enum": list(behavior_ids)},
            "score": _NULLABLE_INT,
            "evidence": _STR,
            "good": _STR,
            "improve": _STR,
            "say_instead": _STR,
        }
    )
    checklist_id = {"type": "string", "enum": list(checklist_keys)} if checklist_keys else _STR
    item = _obj(
        {
            "id": checklist_id,
            "result": {"type": "string", "enum": ["yes", "no", "na"]},
            "evidence": _STR,
        }
    )
    return _obj(
        {
            "behaviors": {"type": "array", "items": behavior},
            "checklist": {"type": "array", "items": item},
            "strengths": {"type": "array", "items": _STR},
            "growth": {"type": "array", "items": _STR},
            "summary": _STR,
            "next_drill": _STR,
            "follow_up_questions": {"type": "array", "items": _STR},
            "line_tips": {
                "type": "array",
                "items": _obj({"reply": {"type": "integer"}, "better": _STR}),
            },
        }
    )


def survey_schema(survey_ids: list[str]) -> dict:
    """The customer's survey answers, one per survey marker."""
    answer = _obj(
        {
            "id": {"type": "string", "enum": list(survey_ids)},
            "score": {"type": "integer"},
            "reason": _STR,
        }
    )
    return _obj({"answers": {"type": "array", "items": answer}})


def tutor_lesson_schema() -> dict:
    """A short product lesson and three check questions with their answer keys."""
    point = _obj({"title": _STR, "explain": _STR})
    question = _obj({"question": _STR, "answer": _STR})
    return _obj(
        {
            "intro": _STR,
            "points": {"type": "array", "items": point},
            "questions": {"type": "array", "items": question},
        }
    )


def tutor_grade_schema() -> dict:
    """The tutor's verdict on one answer."""
    return _obj({"correct": {"type": "boolean"}, "feedback": _STR, "ideal": _STR})


def scenario_schema() -> dict:
    """A practice roleplay drafted from a sentence or two."""
    customer = _obj(
        {
            "name": _STR,
            "role": _STR,
            "voice": {"type": "string", "enum": ["female", "male"]},
            "persona": _STR,
            "mood": _STR,
            "situation": _STR,
            "hidden_objections": {"type": "array", "items": _STR},
            "wins_if": _STR,
            "walks_away_if": _STR,
        }
    )
    return _obj(
        {
            "title": _STR,
            "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard"]},
            "public_brief": _STR,
            "customer": customer,
            "opening_line": _STR,
            "minutes": {"type": "integer"},
            "goals": {
                "type": "array",
                "items": _obj({"name": _STR, "description": _STR, "weight": {"type": "integer"}}),
            },
        }
    )

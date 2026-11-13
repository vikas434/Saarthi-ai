"""Delivery analytics for a practice call, computed from the transcript alone (no model call).

Word choice (filler words, weak words, repeated sentence starters, reply length), listening
(talk time, longest monologue, questions asked) and, for spoken replies, pace in words per minute.
"""

from __future__ import annotations

import re
from collections import Counter

FILLERS = ("um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm", "you know", "i mean", "basically",
           "literally")  # fmt: skip
WEAK_WORDS = ("i think", "i guess", "maybe", "just", "kind of", "sort of", "probably",
              "hopefully", "perhaps", "i feel like")  # fmt: skip
QUESTION_STARTS = frozenset(
    [
        "what",
        "how",
        "why",
        "when",
        "where",
        "who",
        "which",
        "can",
        "could",
        "would",
        "will",
        "do",
        "does",
        "did",
        "is",
        "are",
        "should",
        "shall",
        "may",
        "have",
        "has",
    ]
)
PACE_SLOW, PACE_FAST = 110, 170  # words per minute; conversational in between
FILLER_WATCH_PERCENT = 4.0
WEAK_WATCH_PERCENT = 3.0
STARTER_WATCH_PERCENT = 40
STARTER_MIN_SENTENCES = 3
TALK_WATCH_PERCENT = 60
MONOLOGUE_WATCH_WORDS = 120
MONOLOGUE_WATCH_SECONDS = 60
REPLY_WATCH_WORDS = 60


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _count_phrases(words: list[str], phrases: tuple[str, ...]) -> Counter:
    joined = " " + " ".join(words) + " "
    return Counter({p: joined.count(f" {p} ") for p in phrases if f" {p} " in joined})


def _percent(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _sentences(text: str) -> list[str]:
    return [s for s in (p.strip() for p in re.split(r"[.!?]+", text)) if _words(s)]


def _questions(text: str) -> int:
    marks = text.count("?")
    if marks:
        return marks
    words = _words(text)
    return 1 if words and words[0] in QUESTION_STARTS else 0


def _word_metric(metric_id: str, name: str, words: list[str], phrases, watch: float) -> dict:
    counts = _count_phrases(words, phrases)
    total = sum(counts.values())
    percent = _percent(total, len(words))
    top = [p for p, _ in counts.most_common(3)]
    return {
        "id": metric_id,
        "group": "word_choice",
        "name": name,
        "count": total,
        "percent": percent,
        "top": top,
        "value": f"{total} ({percent:g}%)",
        "detail": ("Most used: " + ", ".join(f'"{t}"' for t in top)) if top else "None heard.",
        "verdict": "watch" if percent >= watch else "good",
    }


def _starters(replies: list[str]) -> dict:
    sentences = [s for r in replies for s in _sentences(r)]
    firsts = Counter(_words(s)[0] for s in sentences)
    word, count = firsts.most_common(1)[0] if firsts else ("", 0)
    percent = round(_percent(count, len(sentences)))
    watch = len(sentences) >= STARTER_MIN_SENTENCES and percent >= STARTER_WATCH_PERCENT
    return {
        "id": "sentence_starters",
        "group": "word_choice",
        "name": "Sentence starters",
        "word": word,
        "percent": percent,
        "value": f'"{word}" {percent}%' if word else "–",
        "detail": f'{percent}% of your sentences start with "{word}". Vary how you open.'
        if watch
        else "Good variety in how you start sentences.",
        "verdict": "watch" if watch else "good",
    }


def _listening(agent_turns: list[dict], customer_words: int, agent_words: int) -> list[dict]:
    you = round(_percent(agent_words, agent_words + customer_words))
    longest = max(agent_turns, key=lambda t: len(_words(t["agent_text"])), default=None)
    long_words = len(_words(longest["agent_text"])) if longest else 0
    long_secs = (longest or {}).get("agent_seconds")
    asked = sum(_questions(t["agent_text"]) for t in agent_turns)
    too_long = long_words > MONOLOGUE_WATCH_WORDS or (long_secs or 0) > MONOLOGUE_WATCH_SECONDS
    return [
        {
            "id": "talk_time",
            "group": "listening",
            "name": "Talk time",
            "you_percent": you,
            "value": f"You {you}% · Customer {100 - you if agent_words + customer_words else 0}%",
            "detail": "You talked more than the customer. Ask, then listen."
            if you > TALK_WATCH_PERCENT
            else "Good balance: the customer did plenty of the talking.",
            "verdict": "watch" if you > TALK_WATCH_PERCENT else "good",
        },
        {
            "id": "monologue",
            "group": "listening",
            "name": "Longest reply",
            "words": long_words,
            "seconds": long_secs,
            "value": f"{long_words} words" + (f" · {long_secs:g}s" if long_secs else ""),
            "detail": "Break long explanations up with a check-in question."
            if too_long
            else "No long monologues.",
            "verdict": "watch" if too_long else "good",
        },
        {
            "id": "questions",
            "group": "listening",
            "name": "Questions asked",
            "count": asked,
            "value": str(asked),
            "detail": "Ask more open questions to learn what the customer needs."
            if asked < 2
            else "You asked questions to understand the customer.",
            "verdict": "watch" if asked < 2 else "good",
        },
    ]


def _pace(agent_turns: list[dict]) -> dict | None:
    spoken = [t for t in agent_turns if (t.get("agent_seconds") or 0) > 0]
    seconds = sum(t["agent_seconds"] for t in spoken)
    if not spoken or seconds <= 0:
        return None
    wpm = round(sum(len(_words(t["agent_text"])) for t in spoken) / seconds * 60)
    band = "slow" if wpm < PACE_SLOW else "fast" if wpm > PACE_FAST else "conversational"
    return {
        "id": "pace",
        "group": "delivery",
        "name": "Pace",
        "wpm": wpm,
        "band": band,
        "value": f"{wpm} words/min",
        "detail": {
            "slow": "A little slow. Keep your energy up.",
            "fast": "Quite fast. Slow down so the customer can follow.",
            "conversational": "A relaxed, conversational pace.",
        }[band],
        "verdict": "good" if band == "conversational" else "watch",
    }


EYE_CONTACT_GOOD = 60  # percent of the time facing the screen
FACE_IN_FRAME_GOOD = 80
SMILE_WATCH_BELOW = 5
TENSE_WATCH_ABOVE = 25


def _weighted(rows: list[dict], key: str) -> float:
    frames = sum(r["frames"] for r in rows)
    return round(sum(r[key] * r["frames"] for r in rows) / frames, 1) if frames else 0.0


def _camera(agent_turns: list[dict]) -> list[dict]:
    """On-camera metrics, from the per-reply numbers the browser worked out. No images."""
    rows = [
        {**t["camera"], "reply": n}
        for n, t in enumerate(agent_turns, start=1)
        if t.get("camera") and t["camera"].get("frames")
    ]
    if not rows:
        return []
    face, eye = _weighted(rows, "face_pct"), _weighted(rows, "eye_contact_pct")
    smile, tense = _weighted(rows, "smile_pct"), _weighted(rows, "tense_pct")
    weakest = min(rows, key=lambda r: r["eye_contact_pct"])
    eye_detail = (
        "You kept facing the customer."
        if eye >= EYE_CONTACT_GOOD
        else f"You often looked away; most of all around reply {weakest['reply']}. "
        "Look at the customer, especially when you talk about price."
    )
    return [
        {
            "id": "eye_contact",
            "group": "camera",
            "name": "Eye contact",
            "percent": eye,
            "value": f"{eye:g}% of the time",
            "detail": eye_detail,
            "verdict": "good" if eye >= EYE_CONTACT_GOOD else "watch",
        },
        {
            "id": "smile",
            "group": "camera",
            "name": "Smiling",
            "percent": smile,
            "value": f"{smile:g}% of the time",
            "detail": "A warm, friendly face."
            if smile >= SMILE_WATCH_BELOW
            else "You rarely smiled. A smile when you greet and agree makes you sound warmer.",
            "verdict": "good" if smile >= SMILE_WATCH_BELOW else "watch",
        },
        {
            "id": "tense_face",
            "group": "camera",
            "name": "Tense expression",
            "percent": tense,
            "value": f"{tense:g}% of the time",
            "detail": "You looked tense or frowned often. Relax your brow, especially under pressure."
            if tense > TENSE_WATCH_ABOVE
            else "You looked relaxed.",
            "verdict": "watch" if tense > TENSE_WATCH_ABOVE else "good",
        },
        {
            "id": "face_in_frame",
            "group": "camera",
            "name": "Face in frame",
            "percent": face,
            "value": f"{face:g}% of the time",
            "detail": "You stayed in view."
            if face >= FACE_IN_FRAME_GOOD
            else "You were often out of view. Sit centred, facing the camera.",
            "verdict": "good" if face >= FACE_IN_FRAME_GOOD else "watch",
        },
    ]


def analyze(turns: list[dict]) -> dict:
    """Metrics for the agent's side of the call. turns are the stored turns of a session."""
    agent_turns = [t for t in turns if t.get("agent_text")]
    replies = [t["agent_text"] for t in agent_turns]
    words = [w for r in replies for w in _words(r)]
    customer_words = sum(len(_words(t.get("customer_text") or "")) for t in turns)
    average = round(len(words) / len(replies)) if replies else 0
    metrics = [
        _word_metric("filler_words", "Filler words", words, FILLERS, FILLER_WATCH_PERCENT),
        _word_metric("weak_words", "Weak words", words, WEAK_WORDS, WEAK_WATCH_PERCENT),
        _starters(replies),
        {
            "id": "reply_length",
            "group": "word_choice",
            "name": "Reply length",
            "average_words": average,
            "value": f"{average} words on average",
            "detail": "Long replies; say it in fewer words."
            if average > REPLY_WATCH_WORDS
            else "Replies were short and to the point.",
            "verdict": "watch" if average > REPLY_WATCH_WORDS else "good",
        },
        *_listening(agent_turns, customer_words, len(words)),
    ]
    pace = _pace(agent_turns)
    if pace:
        metrics.append(pace)
    camera = _camera(agent_turns)
    metrics.extend(camera)
    return {"metrics": metrics, "spoken": pace is not None, "camera": bool(camera)}

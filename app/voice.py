"""The customer's human voice: ElevenLabs Flash v2.5, with a monthly character cap.

Only the AI customer's own lines are sent to ElevenLabs, never the agent's words. When there is no
key, the month's characters are used up, or ElevenLabs refuses, the route answers 204 and the page
speaks with the browser's voice instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from app import coach, usage
from app.config import env
from app.db import engine

logger = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
OUTPUT_FORMAT = "mp3_22050_32"  # small files; plenty for a phone-call voice
TIMEOUT_SECONDS = 15.0
MAX_LINE_CHARS = 600
DEFAULT_MONTHLY_CHAR_CAP = (
    18000  # free plan: about 10,000 credits; Flash uses about half a credit a character
)
CACHE_SIZE = 64
TENSE_MOODS = (
    "frustrat",
    "annoy",
    "angry",
    "upset",
    "rush",
    "blunt",
    "impatient",
    "skeptic",
    "guard",
)
REFUSALS = {401, 402, 403, 429}

_config = json.loads((coach.CONFIG_DIR / "voices.json").read_text(encoding="utf-8"))
MODEL = _config["model"]
VOICES: dict[str, list[str]] = {g: list(_config[g].values()) for g in ("female", "male")}

_lock = threading.Lock()
_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_refused_month: str | None = None  # after ElevenLabs refuses, stop asking until next month


def reset_for_tests() -> None:
    global _refused_month
    with _lock:
        _cache.clear()
        _refused_month = None


def all_voice_ids() -> list[str]:
    return VOICES["female"] + VOICES["male"]


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def monthly_cap() -> int:
    try:
        return int(env("ELEVENLABS_MONTHLY_CHAR_CAP") or DEFAULT_MONTHLY_CHAR_CAP)
    except ValueError:
        return DEFAULT_MONTHLY_CHAR_CAP


def characters_this_month() -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with engine().connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COALESCE(SUM(input_tokens), 0) FROM usage "
                    "WHERE kind = 'voice' AND created_at >= :start"
                ),
                {"start": start.isoformat(timespec="seconds")},
            ).scalar_one()
        )


def available() -> bool:
    """True when the customer can speak with the human voice right now."""
    if not env("ELEVENLABS_API_KEY") or _refused_month == _month():
        return False
    return characters_this_month() < monthly_cap()


def pick_voice(customer: dict) -> str:
    """Same customer, same voice: chosen from the customer's voice type and name."""
    pool = VOICES.get(str(customer.get("voice", "")).lower()) or all_voice_ids()
    digest = hashlib.sha256(str(customer.get("name", "")).encode()).digest()
    return pool[digest[0] % len(pool)]


def settings_for(customer: dict) -> dict:
    """Tense customers get a less steady, more expressive delivery."""
    mood = str(customer.get("mood", "")).lower()
    tense = any(word in mood for word in TENSE_MOODS)
    return {"stability": 0.3 if tense else 0.55, "similarity_boost": 0.75, "speed": 1.0}


def speak(line: str, customer: dict) -> bytes | None:
    """MP3 bytes of the customer saying this line, or None to use the browser voice."""
    global _refused_month
    line = line.strip()[:MAX_LINE_CHARS]
    if not line or not available():
        return None
    voice_id = pick_voice(customer)
    key = (voice_id, line)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    if characters_this_month() + len(line) > monthly_cap():
        return None
    try:
        res = httpx.post(
            API.format(voice_id=voice_id),
            headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "accept": "audio/mpeg"},
            params={"output_format": OUTPUT_FORMAT},
            json={"text": line, "model_id": MODEL, "voice_settings": settings_for(customer)},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("human voice unavailable: %s", type(exc).__name__)
        return None
    if res.status_code in REFUSALS:
        logger.error("ElevenLabs refused (%s); browser voice until next month", res.status_code)
        _refused_month = _month()
        return None
    if res.status_code != 200 or not res.content:
        logger.warning("ElevenLabs answered %s; using the browser voice", res.status_code)
        return None
    usage.record(MODEL, len(line), 0, kind="voice")
    with _lock:
        _cache[key] = res.content
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return res.content

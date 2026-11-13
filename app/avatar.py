"""The customer's face on a call: a real-time Anam avatar that says the customer's lines.

Saarthi still decides every line (the model plays the customer and keeps the hidden objections on
the server). Anam only gets the customer's lines to speak: its own LLM is switched off with
`CUSTOMER_CLIENT_V1`, and the agent's microphone never goes to Anam. The server hands the page a
short-lived session token; the API key never leaves the server.

Without ANAM_API_KEY, past the month's minutes, or if Anam refuses, the token route answers 204 and
the call runs as before (human voice or browser voice, no video).

    python -m app.avatar list     # stock avatars and voices for config/avatars.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from functools import lru_cache

import httpx
from sqlalchemy import text

from app import events, usage
from app.config import CONFIG_DIR, env
from app.db import engine

logger = logging.getLogger(__name__)

API = "https://api.anam.ai/v1"
TOKEN_URL = f"{API}/auth/session-token"
CLIENT_LLM = "CUSTOMER_CLIENT_V1"  # no Anam LLM: the page tells the avatar what to say
SDK_VERSION = "4.29.2"
TIMEOUT_SECONDS = 10.0
TOKEN_SECONDS = 120  # the page must start the stream within two minutes
DEFAULT_MONTHLY_MINUTES = 30  # Anam's free plan
GRACE_SECONDS = 60  # a call may run a little past its time limit while it wraps up
# Anam's network, for the page's Content-Security-Policy (docs: security/network).
CONNECT_SOURCES = (
    "https://api.anam.ai",
    "wss://connect.anam.ai",
    "wss://connect-eu.anam.ai",
    "wss://connect-us.anam.ai",
    "https://connect.anam.ai",
    "https://connect-eu.anam.ai",
    "https://connect-us.anam.ai",
)
SCRIPT_SOURCE = "https://esm.sh"


@lru_cache(maxsize=1)
def _pools() -> dict:
    data = json.loads((CONFIG_DIR / "avatars.json").read_text(encoding="utf-8"))
    return {"female": data.get("female") or [], "male": data.get("male") or []}


def reset_for_tests() -> None:
    _pools.cache_clear()


def monthly_minutes() -> int:
    try:
        return int(env("ANAM_MONTHLY_MINUTE_CAP") or DEFAULT_MONTHLY_MINUTES)
    except ValueError:
        return DEFAULT_MONTHLY_MINUTES


def seconds_this_month() -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with engine().connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COALESCE(SUM(input_tokens), 0) FROM usage "
                    "WHERE kind = 'avatar' AND created_at >= :start"
                ),
                {"start": start.isoformat(timespec="seconds")},
            ).scalar_one()
        )


def configured() -> bool:
    return bool(env("ANAM_API_KEY")) and any(_pools().values())


def available() -> bool:
    """True when a call can start with the video customer right now."""
    return configured() and seconds_this_month() < monthly_minutes() * 60


def pick(customer: dict) -> dict:
    """Same customer, same face and voice: the voice type picks the pool, the name the pair."""
    pools = _pools()
    wanted = str(customer.get("voice", "")).lower()
    pool = pools.get(wanted) or pools["female"] + pools["male"]
    digest = hashlib.sha256(str(customer.get("name", "")).encode()).digest()
    return pool[digest[0] % len(pool)]


def session_token(customer: dict, minutes: int) -> str | None:
    """A one-session Anam token for this customer, or None to run the call without video."""
    if not available():
        return None
    seconds = minutes * 60 + GRACE_SECONDS
    if seconds_this_month() + seconds > monthly_minutes() * 60:
        return None
    face = pick(customer)
    body = {
        "personaConfig": {
            "name": str(customer.get("name", "Customer"))[:40],
            "avatarId": face["avatar_id"],
            "voiceId": face["voice_id"],
            "llmId": CLIENT_LLM,
            "skipGreeting": True,
            "maxSessionLengthSeconds": seconds,
        },
        "maxSessions": 1,
        "expiresInSeconds": TOKEN_SECONDS,
    }
    try:
        res = httpx.post(
            TOKEN_URL,
            headers={"Authorization": f"Bearer {env('ANAM_API_KEY')}"},
            json=body,
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        events.fallback("avatar.anam", exc)
        return None
    token = res.json().get("sessionToken") if res.status_code == 200 else None
    if not token:
        logger.warning("Anam refused a session token: %s", res.status_code)
        events.fallback("avatar.anam", f"status {res.status_code}")
        return None
    # Planned seconds count against the month's minutes; Anam bills what is actually used.
    usage.record("anam", seconds, 0, kind="avatar")
    return token


def _list(kind: str) -> list[dict]:
    res = httpx.get(
        f"{API}/{kind}",
        headers={"Authorization": f"Bearer {env('ANAM_API_KEY')}"},
        params={"perPage": 100},
        timeout=TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    return res.json().get("data", [])


def _main(argv: list[str]) -> int:
    if argv[1:] != ["list"] or not env("ANAM_API_KEY"):
        print("usage: ANAM_API_KEY in .env, then python -m app.avatar list", file=sys.stderr)
        return 2
    for a in _list("avatars"):
        print("avatar", a.get("id"), a.get("displayName"), a.get("variantName"), sep="\t")
    for v in _list("voices"):
        print(
            "voice", v.get("id"), v.get("displayName"), v.get("gender"), v.get("country"), sep="\t"
        )
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

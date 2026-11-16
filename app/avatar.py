"""The customer's face on a call: a real-time Anam avatar that says the customer's lines.

Saarthi still decides every line (the model plays the customer and keeps the hidden objections on
the server). Anam only gets the customer's lines to speak: its own LLM is switched off with
`CUSTOMER_CLIENT_V1`, and the agent's microphone never goes to Anam. The server hands the page a
short-lived session token; the API key never leaves the server.

Without ANAM_API_KEY, once the plan's minutes are used up, or if Anam refuses, the token route
answers 204 and the call runs as before (human voice, no video). Minutes left are what Anam says
was really used since the plan's reset day, so nothing is reserved or blocked in advance; the page
shows the number so people know how much video is left.

    python -m app.avatar list     # stock avatars and voices for config/avatars.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
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
SESSIONS_URL = f"{API}/sessions"
USAGE_CACHE_SECONDS = 20  # how long Anam's answer is reused
OPEN_SESSION_MAX_SECONDS = 600  # a session still running counts for no more than this
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


_usage_cache: tuple[float, int] | None = None


def reset_for_tests() -> None:
    _pools.cache_clear()
    forget()


def forget() -> None:
    """Ask Anam again next time (a call just ended)."""
    global _usage_cache
    _usage_cache = None


def monthly_minutes() -> int:
    try:
        return int(env("ANAM_MONTHLY_MINUTE_CAP") or DEFAULT_MONTHLY_MINUTES)
    except ValueError:
        return DEFAULT_MONTHLY_MINUTES


def reset_day() -> int:
    """Day of the month the plan's minutes renew (Anam shows it on the plan page)."""
    try:
        return min(28, max(1, int(env("ANAM_RESET_DAY") or 1)))
    except ValueError:
        return 1


def period_start(now: datetime | None = None) -> datetime:
    """Start of the current plan month: the latest reset day that is not in the future."""
    now = now or datetime.now(UTC)
    start = now.replace(day=reset_day(), hour=0, minute=0, second=0, microsecond=0)
    if start > now:
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=reset_day())
    return start


def _local_seconds(start: datetime) -> int:
    """Planned seconds we recorded ourselves; only used when Anam can't be asked."""
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


def _anam_seconds(start: datetime, now: datetime) -> int:
    res = httpx.get(
        SESSIONS_URL,
        headers={"Authorization": f"Bearer {env('ANAM_API_KEY')}"},
        params={"perPage": 100},
        timeout=TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    total = 0.0
    for row in res.json().get("data", []):
        began = datetime.fromisoformat(str(row.get("startTime", "")))
        if began < start:
            continue
        length = (row.get("sessionLengthMs") or 0) / 1000
        if not length and not row.get("endTime"):  # still running
            length = min((now - began).total_seconds(), OPEN_SESSION_MAX_SECONDS)
        total += max(0.0, length)
    return int(total)


def seconds_used() -> int:
    """Video seconds used this plan month, from Anam's own record (ours if Anam can't be asked)."""
    global _usage_cache
    now = datetime.now(UTC)
    if _usage_cache and time.monotonic() - _usage_cache[0] < USAGE_CACHE_SECONDS:
        return _usage_cache[1]
    start = period_start(now)
    try:
        used = _anam_seconds(start, now)
    except (httpx.HTTPError, ValueError) as exc:
        events.fallback("avatar.usage", exc)
        used = _local_seconds(start)
    _usage_cache = (time.monotonic(), used)
    return used


def seconds_left() -> int:
    return max(0, monthly_minutes() * 60 - seconds_used())


def configured() -> bool:
    return bool(env("ANAM_API_KEY")) and any(_pools().values())


def available() -> bool:
    """True when a call can start with the video customer right now."""
    return configured() and seconds_left() > 0


def status() -> dict | None:
    """What the page needs: the SDK version and the minutes left, or None for no video."""
    if not available():
        return None
    return {"sdk": SDK_VERSION, **minutes()}


def minutes() -> dict | None:
    """Video minutes left this plan month (shown at the top of the page), None without a key."""
    if not configured():
        return None
    return {"minutes_left": round(seconds_left() / 60, 1), "minutes_total": monthly_minutes()}


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
    seconds = min(minutes * 60 + GRACE_SECONDS, seconds_left())  # never plan past what is left
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
    # Our own record of planned seconds: only a fallback, Anam's usage is what the page shows.
    usage.record("anam", seconds, 0, kind="avatar")
    forget()
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

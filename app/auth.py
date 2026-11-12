"""Who is calling: Clerk session tokens, an env allow-list, and two roles.

TEACHER_EMAIL is the admin (sees every call, edits Setup). STUDENT_EMAILS are agents (own calls
only). Anyone else who signs in is recorded in access_requests, then either becomes an agent
(OPEN_SIGNUP=1, ADR 0004) or gets ACCESS_PENDING.

AUTH_DEV_BYPASS=1 lets tests and local runs send "X-Dev-User: <email>" instead of a token. It is
refused on a hosted server (RAILWAY_ENVIRONMENT or RENDER set). Bypass skips token checks only;
the allow-list still decides the role.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Literal

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.config import env

logger = logging.getLogger(__name__)

ACCESS_PENDING = "Your request is received. We will review and approve."
CLERK_API = "https://api.clerk.com/v1"
JWKS_TTL_SECONDS = 3600
EMAIL_TTL_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 10.0
CLOCK_SKEW_SECONDS = 30
SIGNUP_LOG_TTL_SECONDS = 600  # write a newcomer's sign-in to the log at most this often
HOSTED_ENV_MARKERS = ("RAILWAY_ENVIRONMENT", "RENDER")
# Major version of Clerk's browser script. Clerk refuses sign-in from majors it has retired.
DEFAULT_CLERK_JS_VERSION = "6"
DEFAULT_CLERK_UI_VERSION = "1"  # @clerk/ui, the sign-in screens clerk-js 6 loads separately

Role = Literal["admin", "agent"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    role: Role


class AuthError(Exception):
    """Sign-in failed. status is 401 (no or bad token), 403 (not on the list) or 503."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _split_emails(raw: str) -> frozenset[str]:
    return frozenset(e.lower() for e in re.split(r"[\s,;]+", raw.strip().strip("\"'")) if e)


def role_for(email: str) -> Role | None:
    """The role for an email from the env allow-list, or None when it is not listed."""
    email = email.strip().lower()
    if email and email in _split_emails(env("TEACHER_EMAIL")):
        return "admin"
    if email and email in _split_emails(env("STUDENT_EMAILS")):
        return "agent"
    return None


def open_signup() -> bool:
    """True when anyone who signs in may practise as an agent."""
    return env("OPEN_SIGNUP") in ("1", "true", "yes")


def dev_bypass_enabled() -> bool:
    if env("AUTH_DEV_BYPASS") not in ("1", "true", "yes"):
        return False
    hosted = [name for name in HOSTED_ENV_MARKERS if env(name)]
    if hosted:
        logger.error("AUTH_DEV_BYPASS ignored on a hosted server (%s is set)", ", ".join(hosted))
        return False
    return True


def clerk_configured() -> bool:
    return bool(env("CLERK_SECRET_KEY") and env("CLERK_PUBLISHABLE_KEY"))


def frontend_api_host(publishable_key: str) -> str:
    """Clerk's Frontend API host is base64-encoded inside the publishable key."""
    encoded = publishable_key.split("_", 2)[-1]
    padded = encoded + "=" * (-len(encoded) % 4)
    return base64.b64decode(padded).decode().rstrip("$")


def public_config() -> dict:
    """What the page needs to start sign-in. Never includes a secret."""
    if clerk_configured():
        pk = env("CLERK_PUBLISHABLE_KEY")
        return {
            "mode": "clerk",
            "publishable_key": pk,
            "frontend_api": frontend_api_host(pk),
            "clerk_js_version": env("CLERK_JS_VERSION", DEFAULT_CLERK_JS_VERSION),
            "clerk_ui_version": env("CLERK_UI_VERSION", DEFAULT_CLERK_UI_VERSION),
        }
    if dev_bypass_enabled():
        return {"mode": "dev"}
    return {"mode": "off"}


# Clerk: signing keys and user emails, cached.

_cache_lock = threading.Lock()
_jwks: tuple[float, dict] | None = None
_emails: dict[str, tuple[float, str]] = {}
_signup_logged: dict[str, float] = {}


def reset_for_tests() -> None:
    with _cache_lock:
        _signup_logged.clear()


def _clerk_get(path: str) -> dict:
    resp = httpx.get(
        f"{CLERK_API}{path}",
        headers={"Authorization": f"Bearer {env('CLERK_SECRET_KEY')}"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_jwks() -> dict:
    global _jwks
    with _cache_lock:
        if _jwks and time.monotonic() - _jwks[0] < JWKS_TTL_SECONDS:
            return _jwks[1]
    keys = _clerk_get("/jwks")
    with _cache_lock:
        _jwks = (time.monotonic(), keys)
    return keys


def _email_for_user(user_id: str) -> str:
    with _cache_lock:
        hit = _emails.get(user_id)
        if hit and time.monotonic() - hit[0] < EMAIL_TTL_SECONDS:
            return hit[1]
    data = _clerk_get(f"/users/{user_id}")
    addresses = data.get("email_addresses") or []
    primary = data.get("primary_email_address_id")
    chosen = next(
        (a for a in addresses if a.get("id") == primary), addresses[0] if addresses else {}
    )
    email = str(chosen.get("email_address") or "").lower()
    if not email:
        raise AuthError(401, "Your account has no email address.")
    with _cache_lock:
        _emails[user_id] = (time.monotonic(), email)
    return email


def _signing_key(token: str):
    kid = jwt.get_unverified_header(token).get("kid")
    for key in _fetch_jwks().get("keys", []):
        if key.get("kid") == kid:
            return RSAAlgorithm.from_jwk(json.dumps(key))
    raise AuthError(401, "Sign-in expired. Please sign in again.")


def _verify_clerk_token(token: str) -> Principal:
    try:
        claims = jwt.decode(
            token,
            _signing_key(token),
            algorithms=["RS256"],
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
    except AuthError:
        raise
    except (jwt.PyJWTError, ValueError) as exc:
        raise AuthError(401, "Sign-in expired. Please sign in again.") from exc
    except httpx.HTTPError as exc:
        logger.error("could not reach Clerk: %s", type(exc).__name__)
        raise AuthError(503, "Sign-in is unavailable right now. Try again shortly.") from exc
    allowed = {p.strip() for p in env("CLERK_AUTHORIZED_PARTIES").split(",") if p.strip()}
    if allowed and claims.get("azp") not in allowed:
        raise AuthError(401, "This sign-in is not for this site.")
    user_id = str(claims["sub"])
    try:
        email = str(claims.get("email") or "").lower() or _email_for_user(user_id)
    except httpx.HTTPError as exc:
        logger.error("could not load Clerk user: %s", type(exc).__name__)
        raise AuthError(503, "Sign-in is unavailable right now. Try again shortly.") from exc
    return _principal(user_id, email)


def _log_newcomer(email: str) -> None:
    """Record a sign-in from outside the allow-list, at most once per SIGNUP_LOG_TTL_SECONDS."""
    now = time.monotonic()
    with _cache_lock:
        last = _signup_logged.get(email)
        if last is not None and now - last < SIGNUP_LOG_TTL_SECONDS:
            return
        _signup_logged[email] = now
    from app import store  # late import: store imports nothing from here

    store.record_access_request(email)


def _principal(user_id: str, email: str) -> Principal:
    email = email.lower()
    role = role_for(email)
    if role is None:
        if not open_signup():
            from app import store

            store.record_access_request(email)
            raise AuthError(403, ACCESS_PENDING)
        _log_newcomer(email)
        role = "agent"
    return Principal(user_id=user_id, email=email, role=role)


def authenticate(authorization: str | None, dev_user: str | None) -> Principal:
    """Resolve the caller or raise AuthError."""
    if dev_user and dev_bypass_enabled():
        email = dev_user.strip().lower()
        return _principal(f"dev:{email}", email)
    if not clerk_configured():
        if dev_bypass_enabled():
            raise AuthError(401, "Not signed in.")
        raise AuthError(503, "Sign-in is not configured on this server.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "Not signed in.")
    return _verify_clerk_token(authorization.split(" ", 1)[1].strip())

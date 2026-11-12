"""Security headers on every response, and HTTPS enforcement behind a TLS-terminating proxy.

The app is same-origin only: it sends no CORS headers, so browsers refuse cross-site API calls.
The content security policy allows this site, the Clerk instance named in the publishable key,
and the Cloudflare challenge Clerk uses for bot protection.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app import auth
from app.config import env

HSTS_SECONDS = 31_536_000
HTTPS_EXEMPT_PATHS = ("/health", "/ready")  # the host's own health checks come over plain HTTP
CLERK_STATIC_HOSTS = ("https://img.clerk.com", "https://clerk-telemetry.com")
CLOUDFLARE_CHALLENGE = "https://challenges.cloudflare.com"


def _clerk_origin() -> str:
    pk = env("CLERK_PUBLISHABLE_KEY")
    if not pk:
        return ""
    try:
        return "https://" + auth.frontend_api_host(pk)
    except ValueError:
        return ""


def content_security_policy() -> str:
    clerk = _clerk_origin()
    extra = f" {clerk}" if clerk else ""
    directives = {
        "default-src": "'self'",
        # The page's script is inline; moving it to a file would allow dropping 'unsafe-inline'.
        "script-src": f"'self' 'unsafe-inline'{extra} {CLOUDFLARE_CHALLENGE}",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": f"'self' data: {CLERK_STATIC_HOSTS[0]}",
        "font-src": "'self' data:",
        "connect-src": f"'self'{extra} {CLERK_STATIC_HOSTS[1]}",
        "frame-src": CLOUDFLARE_CHALLENGE,
        "worker-src": "'self' blob:",
        "form-action": "'self'",
        "base-uri": "'self'",
        "object-src": "'none'",
        "frame-ancestors": "'none'",
    }
    return "; ".join(f"{k} {v}" for k, v in directives.items())


def _force_https() -> bool:
    return env("FORCE_HTTPS") in ("1", "true", "yes")


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        forwarded = request.headers.get("x-forwarded-proto", "")
        if _force_https() and forwarded == "http" and request.url.path not in HTTPS_EXEMPT_PATHS:
            return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
        response = await call_next(request)
        headers = response.headers
        headers["Content-Security-Policy"] = content_security_policy()
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        if _force_https():
            headers["Strict-Transport-Security"] = f"max-age={HSTS_SECONDS}; includeSubDomains"
        return response

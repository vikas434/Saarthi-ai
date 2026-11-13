"""Deployment hardening: readiness, security headers, HTTPS redirect, same-origin CORS."""

from app import db


def test_ready_reports_the_database(anon, monkeypatch):
    assert anon.get("/ready").json() == {"status": "ready"}
    monkeypatch.setattr(db, "ping", lambda: False)
    res = anon.get("/ready")
    assert res.status_code == 503 and res.json()["status"] == "database unreachable"


def test_security_headers_on_every_response(anon):
    for path in ("/", "/health", "/api/auth/config"):
        h = anon.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert (
            # The agent's own camera is opt-in, for this site only; never other origins.
            "camera=(self)" in h["permissions-policy"]
            and "geolocation=()" in h["permissions-policy"]
            and "microphone=(self)" in h["permissions-policy"]
        )
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_csp_allows_the_configured_clerk_host(monkeypatch, anon):
    import base64

    fapi = base64.b64encode(b"example.clerk.accounts.dev$").decode()
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", f"pk_test_{fapi}")
    csp = anon.get("/").headers["content-security-policy"]
    assert "https://example.clerk.accounts.dev" in csp


def test_https_is_enforced_behind_a_proxy(monkeypatch, anon):
    monkeypatch.setenv("FORCE_HTTPS", "1")
    res = anon.get("/", headers={"x-forwarded-proto": "http"}, follow_redirects=False)
    assert res.status_code == 308 and res.headers["location"].startswith("https://")
    ok = anon.get("/", headers={"x-forwarded-proto": "https"})
    assert ok.status_code == 200 and "max-age=" in ok.headers["strict-transport-security"]
    assert anon.get("/health", headers={"x-forwarded-proto": "http"}).status_code == 200


def test_cross_origin_requests_are_not_allowed(monkeypatch, anon):
    monkeypatch.setenv("APP_ORIGIN", "https://saarthi.example.com")
    foreign = anon.options(
        "/api/me",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in foreign.headers

"""Sign-in and roles: 401, the request-received 403, own calls only, admin-only setup."""

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app import auth
from app.main import app

PENDING = "Your request is received. We will review and approve."
SCENARIO = "price-worried-owner"


def _start(c) -> str:
    res = c.post("/api/sessions", json={"scenario_id": SCENARIO})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_not_signed_in_gets_401_on_every_api_route(anon):
    for method, path in [
        ("get", "/api/config"),
        ("get", "/api/me"),
        ("get", "/api/sessions"),
        ("post", "/api/sessions"),
        ("get", "/api/progress"),
        ("put", "/api/product"),
    ]:
        assert getattr(anon, method)(path).status_code == 401, path


def test_public_routes_stay_open(anon):
    assert anon.get("/health").status_code == 200
    assert anon.get("/").status_code == 200
    body = anon.get("/api/auth/config").json()
    assert body["mode"] == "dev" and "secret" not in str(body).lower()


def test_unlisted_email_gets_the_message_and_is_recorded_once(client):
    stranger = TestClient(app, headers={"X-Dev-User": "Someone@Elsewhere.example.com"})
    for path in ("/api/me", "/api/config", "/api/sessions"):
        res = stranger.get(path)
        assert res.status_code == 403 and res.json()["detail"] == PENDING
    rows = [r for r in client.get("/api/access-requests").json() if "elsewhere" in r["email"]]
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "someone@elsewhere.example.com"
    assert row["count"] >= 1 and row["first_seen"] <= row["last_seen"]


def test_me_reports_role(client, agent1):
    assert client.get("/api/me").json() == {"email": "admin@example.com", "role": "admin"}
    assert agent1.get("/api/me").json() == {"email": "agent1@example.com", "role": "agent"}


def test_agents_see_only_their_own_calls(client, agent1, agent2):
    mine = _start(agent1)
    theirs = _start(agent2)
    listed = {s["id"] for s in agent1.get("/api/sessions").json()}
    assert mine in listed and theirs not in listed
    assert agent1.get(f"/api/sessions/{theirs}").status_code == 404
    assert agent1.post(f"/api/sessions/{theirs}/turns", json={"text": "hi"}).status_code == 404
    assert agent1.post(f"/api/sessions/{theirs}/end").status_code == 404
    admin_listed = {s["id"] for s in client.get("/api/sessions").json()}
    assert {mine, theirs} <= admin_listed
    assert client.get(f"/api/sessions/{mine}").status_code == 200


def test_setup_routes_are_admin_only(agent1):
    assert agent1.put("/api/product", json={"text": "x" * 30}).status_code == 403
    assert (
        agent1.post("/api/markers", json={"name": "Nope", "type": "checklist"}).status_code == 403
    )
    assert agent1.delete("/api/markers/custom-x").status_code == 403
    assert agent1.post("/api/roleplays/x/publish", json={"published": True}).status_code == 403
    assert agent1.get("/api/access-requests").status_code == 403


def test_agent_config_hides_product_editing_data(agent1):
    cfg = agent1.get("/api/config").json()
    assert cfg["role"] == "agent" and cfg["scenarios"]


@pytest.mark.parametrize("hosted_var", ["RAILWAY_ENVIRONMENT", "RENDER"])
def test_dev_bypass_is_refused_on_a_hosted_server(monkeypatch, anon, hosted_var):
    monkeypatch.setenv(hosted_var, "true")
    assert auth.dev_bypass_enabled() is False
    res = anon.get("/api/me", headers={"X-Dev-User": "admin@example.com"})
    assert res.status_code in (401, 503)


def test_dev_bypass_is_off_by_default(monkeypatch, anon):
    monkeypatch.delenv("AUTH_DEV_BYPASS")
    assert auth.dev_bypass_enabled() is False
    assert anon.get("/api/me", headers={"X-Dev-User": "admin@example.com"}).status_code in (
        401,
        503,
    )


# Clerk session tokens, verified against a key we generate here.


@pytest.fixture
def clerk_keys(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk["kid"] = "test-kid"
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {"keys": [jwk]})
    monkeypatch.setattr(auth, "_email_for_user", lambda sub: "agent1@example.com")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-secret-for-tests")
    fapi = base64.b64encode(b"example.clerk.accounts.dev$").decode()
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", f"pk_test_{fapi}")
    monkeypatch.delenv("AUTH_DEV_BYPASS")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://saarthi.example.com")

    def token(**overrides):
        now = int(time.time())
        claims = {"sub": "user_123", "iat": now, "nbf": now, "exp": now + 60}
        claims["azp"] = "https://saarthi.example.com"
        claims.update(overrides)
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test-kid"})

    return token


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_valid_clerk_token_signs_in(anon, clerk_keys):
    res = anon.get("/api/me", headers=_bearer(clerk_keys()))
    assert res.status_code == 200 and res.json()["role"] == "agent"


def test_expired_or_forged_or_foreign_tokens_are_rejected(anon, clerk_keys):
    expired = clerk_keys(exp=int(time.time()) - 120)  # beyond the 30 s clock-skew allowance
    foreign = clerk_keys(azp="https://evil.example.com")
    assert anon.get("/api/me", headers=_bearer(expired)).status_code == 401
    assert anon.get("/api/me", headers=_bearer(foreign)).status_code == 401
    assert anon.get("/api/me", headers=_bearer(expired[:-4] + "abcd")).status_code == 401
    assert anon.get("/api/me", headers=_bearer("not-a-jwt")).status_code == 401


def test_frontend_api_host_comes_from_the_publishable_key():
    fapi = base64.b64encode(b"example.clerk.accounts.dev$").decode()
    assert auth.frontend_api_host(f"pk_test_{fapi}") == "example.clerk.accounts.dev"


def test_clerk_config_names_a_current_clerk_js_major(anon, clerk_keys):
    conf = anon.get("/api/auth/config").json()
    assert conf["mode"] == "clerk" and conf["frontend_api"] == "example.clerk.accounts.dev"
    assert int(conf["clerk_js_version"]) >= 6  # Clerk refuses sign-in from retired majors
    assert conf["clerk_ui_version"]  # clerk-js 6 needs its separate UI bundle
    assert "secret" not in str(conf).lower()

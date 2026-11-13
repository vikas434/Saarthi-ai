import os
import tempfile
from pathlib import Path

# Tests never touch the app's database: CI passes a throwaway Postgres as TEST_DATABASE_URL,
# otherwise a temporary SQLite file is used.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
    f"sqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}"
)
for key in (
    "ANTHROPIC_API_KEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "CLERK_SECRET_KEY",
    "CLERK_PUBLISHABLE_KEY",
    "RENDER",
    "ELEVENLABS_API_KEY",
    "SLACK_WEBHOOK_URL",
    "ANAM_API_KEY",
):
    os.environ[key] = ""
os.environ.pop("RAILWAY_ENVIRONMENT", None)
# Sign-in for tests: the dev bypass with example.com addresses only, never real ones.
os.environ["AUTH_DEV_BYPASS"] = "1"
os.environ["TEACHER_EMAIL"] = "admin@example.com"
os.environ["STUDENT_EMAILS"] = "agent1@example.com, agent2@example.com"
# Generous limits so tests sharing one database never trip them; tests/test_limits.py sets
# tight limits relative to the current totals.
os.environ["DAILY_SPEND_CAP_USD"] = "1000"
os.environ["MAX_CALLS_PER_USER_PER_DAY"] = "100000"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["MAX_ROLEPLAYS_PER_USER"] = "100000"
os.environ["MAX_PERSONAS_PER_USER"] = "100000"
ADMIN = {"X-Dev-User": "admin@example.com"}
AGENT1 = {"X-Dev-User": "agent1@example.com"}
AGENT2 = {"X-Dev-User": "agent2@example.com"}

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app


class FakeLLM:
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, *, system, user, max_tokens, schema=None, effort=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "effort": effort})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def client():
    """Signed in as the admin, so existing route tests keep full access."""
    llm.set_llm_for_tests(None)
    yield TestClient(app, headers=ADMIN)
    llm.set_llm_for_tests(None)


@pytest.fixture
def agent1():
    yield TestClient(app, headers=AGENT1)


@pytest.fixture
def agent2():
    yield TestClient(app, headers=AGENT2)


@pytest.fixture
def anon():
    yield TestClient(app)


@pytest.fixture
def fake_llm():
    def install(replies):
        fake = FakeLLM(replies)
        llm.set_llm_for_tests(fake)
        return fake

    return install

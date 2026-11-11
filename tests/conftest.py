import os
import tempfile
from pathlib import Path

# Tests never touch the app's database: CI passes a throwaway Postgres as TEST_DATABASE_URL,
# otherwise a temporary SQLite file is used.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
    f"sqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}"
)
for key in ("ANTHROPIC_API_KEY", "LLM_API_KEY", "LLM_BASE_URL"):
    os.environ[key] = ""

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
    llm.set_llm_for_tests(None)
    yield TestClient(app)
    llm.set_llm_for_tests(None)


@pytest.fixture
def fake_llm():
    def install(replies):
        fake = FakeLLM(replies)
        llm.set_llm_for_tests(fake)
        return fake

    return install

import os
import tempfile
from pathlib import Path

os.environ["SAARTHI_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
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

    def complete(self, *, system, user, max_tokens):
        self.calls.append({"system": system, "user": user})
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

"""The model behind the customer and the coach, chosen by env. No key means offline mode."""

from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

from app.config import env

logger = logging.getLogger(__name__)


class LLM(Protocol):
    name: str

    def complete(self, *, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, base_url: str = "") -> None:
        from anthropic import Anthropic

        self.name = f"anthropic:{model}"
        self._model = model
        self._client = Anthropic(api_key=api_key, base_url=base_url or None)

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


class OpenAICompatibleLLM:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.name = f"openai_compatible:{model}"
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        resp = httpx.post(
            self._url,
            headers=self._headers,
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"].get("content") or "")


_override: LLM | None = None


def set_llm_for_tests(llm: LLM | None) -> None:
    global _override
    _override = llm


def get_llm() -> LLM | None:
    """The configured model, or None when no credentials are set (offline demo mode)."""
    if _override is not None:
        return _override
    provider = env("LLM_PROVIDER", "anthropic")
    model = env("LLM_MODEL", "claude-haiku-4-5-20251001")
    if provider == "openai_compatible":
        if not env("LLM_BASE_URL"):
            return None
        return OpenAICompatibleLLM(env("LLM_API_KEY"), model, env("LLM_BASE_URL"))
    key = env("LLM_API_KEY") or env("ANTHROPIC_API_KEY")
    if not key:
        return None
    return AnthropicLLM(key, model, env("LLM_BASE_URL"))


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])

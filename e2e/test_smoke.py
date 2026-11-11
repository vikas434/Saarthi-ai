"""Browser smoke test: the page loads, an offline call reaches the scorecard, History and Setup
open, and nothing is logged to the console as an error.

    pytest e2e        (needs: pip install -e ".[e2e]" && playwright install chromium)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTUP_SECONDS = 20


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(url: str) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("app did not start")


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Run the app in offline mode with its own database; never the developer's data or key."""
    port = _free_port()
    env = {
        **os.environ,
        "SAARTHI_DB": str(tmp_path_factory.mktemp("db") / "smoke.db"),
        "ANTHROPIC_API_KEY": "",
        "LLM_API_KEY": "",
        "LLM_BASE_URL": "",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_up(url)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def page(base_url: str) -> Iterator[Page]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base_url)
        yield pg
        browser.close()
        assert not errors, f"console errors: {errors}"


def _say(page: Page, text: str, replies_before: int) -> None:
    page.fill("#text", text)
    page.click("#send")
    expect(page.locator("#chat .msg.customer")).to_have_count(replies_before + 1)


def test_offline_call_reaches_the_scorecard_and_tabs_open(page: Page) -> None:
    expect(page.locator("#mode")).to_contain_text("Offline demo mode")
    page.fill("#agent", "Smoke test")
    page.locator("#scenarios button", has_text="Start call").first.click()
    expect(page.locator("#call")).to_be_visible()
    page.uncheck("#speak")
    _say(page, "Hi Meera, thanks for calling. How do you keep your books today?", 1)
    _say(page, "So you spend Sundays in Excel. That sounds tiring. Shall I set up a trial?", 2)
    expect(page.locator("#coach .note")).to_have_count(2)

    page.click("#end")
    expect(page.locator("#report h2", has_text="Scorecard")).to_be_visible()
    expect(page.locator("#report .tile")).to_have_count(4)

    page.click('nav button[data-tab="history"]')
    expect(page.locator("#tab-history")).to_be_visible()
    expect(page.locator("#sessions tr").nth(1)).to_be_visible()

    page.click('nav button[data-tab="setup"]')
    expect(page.locator("#tab-setup")).to_be_visible()
    expect(page.locator("#markers tr", has_text="SQS")).to_be_visible()
    expect(page.locator("#product")).not_to_be_empty()

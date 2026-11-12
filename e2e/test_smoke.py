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
        "DATABASE_URL": f"sqlite:///{tmp_path_factory.mktemp('db') / 'smoke.db'}",
        "ANTHROPIC_API_KEY": "",
        "LLM_API_KEY": "",
        "LLM_BASE_URL": "",
        "CLERK_SECRET_KEY": "",
        "CLERK_PUBLISHABLE_KEY": "",
        "AUTH_DEV_BYPASS": "1",
        "TEACHER_EMAIL": "admin@example.com",
        "STUDENT_EMAILS": "agent@example.com",
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
def page(base_url: str, request: pytest.FixtureRequest) -> Iterator[Page]:
    marker = request.node.get_closest_marker("allow_console")
    allowed = tuple(marker.args) if marker else ()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base_url)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        yield pg
        browser.close()
        unexpected = [e for e in errors if not any(a in e for a in allowed)]
        assert not unexpected, f"console errors: {unexpected}"


def _say(page: Page, text: str, replies_before: int) -> None:
    page.fill("#text", text)
    page.click("#send")
    expect(page.locator("#chat .msg.customer")).to_have_count(replies_before + 1)


def _sign_in(page: Page, email: str) -> None:
    page.fill("#dev-email", email)
    page.click("#dev-sign-in")


@pytest.mark.allow_console("status of 403 (Forbidden)")  # the expected refusal itself
def test_unlisted_email_sees_only_the_request_received_message(page: Page) -> None:
    _sign_in(page, "stranger@example.com")
    expect(page.locator("#gate")).to_have_text(
        "Your request is received. We will review and approve."
    )
    expect(page.locator("header")).to_be_hidden()
    expect(page.locator("main")).to_be_hidden()


def test_agent_does_not_see_setup(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    expect(page.locator("#who")).to_contain_text("agent@example.com · agent")
    expect(page.locator('nav button[data-tab="setup"]')).to_be_hidden()


def test_offline_call_reaches_the_scorecard_and_tabs_open(page: Page) -> None:
    _sign_in(page, "admin@example.com")
    expect(page.locator("#mode")).to_contain_text("Offline demo mode")
    page.fill("#agent", "Smoke test")
    page.evaluate("document.getElementById('hands-free').checked = false")  # typed call
    page.locator("#scenarios button", has_text="Start call").first.click()
    expect(page.locator("#call")).to_be_visible()
    page.uncheck("#speak")
    _say(page, "Hi Meera, thanks for calling. How do you keep your books today?", 1)
    _say(page, "So you spend Sundays in Excel. That sounds tiring. Shall I set up a trial?", 2)
    expect(page.locator("#coach .note")).to_have_count(2)

    page.click("#end")
    expect(page.locator("#report h2", has_text="Call complete")).to_be_visible()
    expect(page.locator("#report .tile")).to_have_count(4)
    expect(page.locator("#report .banner")).to_contain_text("Your score was")
    page.click("#report-tab-analytics")
    expect(page.locator("#report .metric", has_text="Questions asked")).to_be_visible()
    expect(page.locator("#report .tile").first).to_be_hidden()
    page.click("#report-tab-coaching")

    page.click('nav button[data-tab="history"]')
    expect(page.locator("#tab-history")).to_be_visible()
    expect(page.locator("#sessions tr").nth(1)).to_be_visible()

    page.click('nav button[data-tab="setup"]')
    expect(page.locator("#tab-setup")).to_be_visible()
    expect(page.locator("#markers tr", has_text="SQS")).to_be_visible()
    expect(page.locator("#product")).not_to_be_empty()
    expect(page.locator("#access-requests")).to_contain_text("stranger@example.com")


# A stand-in microphone and voice: the fake recogniser "hears" the next scripted line, the fake
# voice finishes speaking at once. Real Chrome speech needs a person and a microphone.
FAKE_VOICE = """
window.__heard = ["Hi Meera, thanks for calling. How do you keep your books today?",
                  "That sounds tiring. What would make Sundays easier?"];
window.__listens = 0;
class FakeRecognition {
  start() {
    window.__listens += 1;
    const line = window.__heard.shift();
    if (line) setTimeout(() => this.onresult({ results: [[{ transcript: line }]] }), 300);
  }
  stop() { setTimeout(() => this.onend && this.onend(), 10); }
}
window.SpeechRecognition = FakeRecognition;
window.webkitSpeechRecognition = FakeRecognition;
Object.defineProperty(window, "speechSynthesis", { value: {
  speak(u) { setTimeout(() => u.onend && u.onend(), 20); }, cancel() {} } });
"""


def test_hands_free_call_listens_sends_and_listens_again(base_url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.add_init_script(FAKE_VOICE)
        sent: list[str] = []
        page.on(
            "request",
            lambda r: sent.append(r.post_data or "") if r.url.endswith("/turns") else None,
        )
        page.goto(base_url)
        page.evaluate("localStorage.clear()")
        page.reload()
        _sign_in(page, "admin@example.com")
        expect(page.locator("#hands-free")).to_be_checked()
        page.locator("#scenarios button", has_text="Start call").first.click()
        expect(page.locator("#clock")).to_contain_text("Time left")
        # Ring, opening line, then two spoken replies go out without any click.
        expect(page.locator("#chat .msg.agent")).to_have_count(2, timeout=20_000)
        expect(page.locator("#chat .msg.customer")).to_have_count(3, timeout=20_000)
        assert len(sent) == 2 and all('"seconds"' in body for body in sent)
        # After the second reply it is listening again, waiting for the agent.
        expect(page.locator("#mic")).to_have_text("■ Done")
        assert page.evaluate("window.__listens") == 3
        page.click("#end")
        expect(page.locator("#report h2", has_text="Call complete")).to_be_visible()
        expect(page.locator("#clock")).to_have_text("")
        browser.close()


def test_build_a_roleplay_from_a_template_and_practise_it(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.click('nav button[data-tab="build"]')
    expect(page.locator("#builder h2")).to_have_text("What's your roleplay about?")
    page.locator(".chip", has_text="Cold sales call").click()
    expect(page.locator("#rp-title")).to_have_value("Cold sales call")
    expect(page.locator("#rp-goals .goal-row")).to_have_count(3)
    page.fill("#rp-title", "My cold call")
    page.click("#rp-save")
    expect(page.locator("#rp-list")).to_contain_text("My cold call")
    expect(page.locator("#rp-list")).to_contain_text("Only you")
    page.locator("#rp-list tr", has_text="My cold call").locator(
        "button", has_text="Practise"
    ).click()
    expect(page.locator("#call-title")).to_have_text("Call with Sanjay")
    page.uncheck("#speak")
    _say(page, "Hi Sanjay, I'll be quick. How do you track stock today?", 1)
    page.click("#end")
    expect(page.locator("#report .tile", has_text="Roleplay goals")).to_be_visible()


@pytest.mark.allow_console("status of 422")  # the refused save itself
def test_builder_shows_what_is_wrong_with_a_roleplay(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.click('nav button[data-tab="build"]')
    page.locator(".chip", has_text="Inbound discovery").click()
    page.fill("#rp-title", "")
    page.click("#rp-save")
    expect(page.locator("#error")).to_contain_text("title")

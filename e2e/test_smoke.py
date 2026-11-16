"""Browser smoke test: the page loads, an offline call reaches the scorecard, History and Setup
open, and nothing is logged to the console as an error.

    pytest e2e        (needs: pip install -e ".[e2e]" && playwright install chromium)
"""

from __future__ import annotations

import os
import re
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
        "ELEVENLABS_API_KEY": "",
        "SLACK_WEBHOOK_URL": "",
        "ANAM_API_KEY": "",
        "AUTH_DEV_BYPASS": "1",
        # The whole suite signs in as two people within a minute or so.
        "RATE_LIMIT_PER_MINUTE": "600",
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
    expect(page.locator('nav button[data-tab="insights"]')).to_be_hidden()


def test_offline_call_reaches_the_scorecard_and_tabs_open(page: Page) -> None:
    _sign_in(page, "admin@example.com")
    expect(page.locator("#mode")).to_contain_text("Offline demo mode")
    page.fill("#agent", "Smoke test")
    page.evaluate("document.getElementById('hands-free').checked = false")  # typed call
    page.locator("#scenarios button", has_text="Start call").first.click()
    expect(page.locator("#call")).to_be_visible()
    page.uncheck("#speak")
    expect(page.locator("#assist-stage")).to_have_text("Opening")  # coach assist: next move
    expect(page.locator("#assist-line")).to_be_hidden()
    page.click("#assist-show")
    expect(page.locator("#assist-line")).to_be_visible()
    _say(page, "Hi Maria, thanks for calling. How do you keep your books today?", 1)
    _say(page, "So you spend Sundays in Excel. That sounds tiring. Shall I set up a trial?", 2)
    expect(page.locator("#coach .note")).to_have_count(2)
    expect(page.locator("#assist-stage")).to_have_text("Discovery")
    page.uncheck("#assist-on")
    expect(page.locator("#assist")).to_be_hidden()

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
window.__heard = ["Hi Maria, thanks for calling. How do you keep your books today?",
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
    expect(page.locator("#call-title")).to_have_text("Call with Tom")
    page.uncheck("#speak")
    _say(page, "Hi Tom, I'll be quick. How do you track stock today?", 1)
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


def test_learn_first_then_practise(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.locator("#scenarios .card").first.locator("button", has_text="Learn first").click()
    expect(page.locator("#tutor h2")).to_contain_text("Learn first:")
    expect(page.locator("#tutor .lesson-point").first).to_be_visible()
    page.click("#tutor-ready")
    for n in range(1, 4):
        expect(page.locator("#tutor h2")).to_have_text(f"Question {n} of 3")
        page.fill("#tutor-answer", "I would check the facts and tell them honestly.")
        page.click("#tutor-send")
        expect(page.locator("#tutor .answer-result")).to_contain_text("Model answer:")
        page.click("#tutor-next")
    expect(page.locator("#tutor-score")).to_contain_text("/ 3 right")
    page.click("#tutor-practise")
    expect(page.locator("#call")).to_be_visible()
    expect(page.locator("#tutor")).to_be_hidden()


def test_dashboard_shows_focus_charts_and_team(page: Page) -> None:
    _sign_in(page, "admin@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    for _ in range(2):
        page.locator("#scenarios button", has_text="Start call").first.click()
        page.uncheck("#speak")
        _say(page, "Hi Maria, how do you keep your books today?", 1)
        page.click("#end")
        expect(page.locator("#report .banner")).to_be_visible()
        page.locator("#report button", has_text="Practise again").click()
    page.click('nav button[data-tab="history"]')
    expect(page.locator("#dashboard .stat").first).to_contain_text("Practice streak")
    expect(page.locator("#focus-charts .chart")).to_have_count(4)
    overall = page.locator("#focus-charts .chart", has_text="Overall score")
    expect(overall.locator("polyline")).to_have_count(1)
    assert overall.locator("circle[r='4']").count() >= 2  # earlier tests share this database
    page.click("#choose-focus")
    page.locator("#focus-picker label", has_text="Filler words").locator("input").uncheck()
    page.click("#save-focus")
    expect(page.locator("#focus-charts .chart")).to_have_count(3)
    expect(page.locator("#team-table")).to_contain_text("admin")


def test_practice_tab_returns_to_the_customer_list(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.locator("#scenarios button", has_text="Start call").first.click()
    page.uncheck("#speak")
    _say(page, "Hi Maria, how do you keep your books today?", 1)
    page.click('nav button[data-tab="practice"]')
    expect(page.locator("#call")).to_be_visible()  # a call in progress stays open
    page.click("#end")
    expect(page.locator("#report .banner")).to_be_visible()
    page.click('nav button[data-tab="history"]')
    expect(page.locator("#sessions th").last).to_have_text("Score")
    page.click('nav button[data-tab="practice"]')
    expect(page.locator("#pick")).to_be_visible()
    expect(page.locator("#report")).to_be_hidden()


# A stand-in for the browser's audio player: records what it was asked to play, ends at once.
FAKE_AUDIO = """
window.__played = [];
window.Audio = class { constructor(src) { this.src = src; }
  play() { window.__played.push(this.src); setTimeout(() => this.onended && this.onended(), 20); return Promise.resolve(); }
  pause() {} };
"""


def test_customer_speaks_with_the_human_voice_when_the_server_has_it(page: Page) -> None:
    def config_with_human_voice(route):
        body = route.fetch().json()
        route.fulfill(json={**body, "voice": "elevenlabs"})

    page.add_init_script(FAKE_AUDIO)
    page.route("**/api/config", config_with_human_voice)
    asked: list[str] = []

    def fake_voice(route):
        asked.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"ID3fake")

    page.route("**/api/sessions/*/voice/*", fake_voice)
    page.reload()
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.locator("#scenarios button", has_text="Start call").first.click()
    expect(page.locator("#chat .msg.customer")).to_have_count(1)
    page.wait_for_function("window.__played.length >= 1")
    _say(page, "Hi Maria, how do you keep your books today?", 1)
    page.wait_for_function("window.__played.length >= 2")
    assert [u.rsplit("/", 1)[-1] for u in asked] == ["0", "1"]  # opening line, then reply 1


def test_scoring_shows_a_clear_waiting_panel(page: Page) -> None:
    def slow_end(route):
        page.wait_for_timeout(800)  # scoring takes a while with a real model
        route.continue_()

    page.route("**/api/sessions/*/end", slow_end)
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.locator("#scenarios button", has_text="Start call").first.click()
    page.uncheck("#speak")
    _say(page, "Hi Maria, how do you keep your books today?", 1)
    page.click("#end")
    expect(page.locator("#scoring")).to_be_visible()
    expect(page.locator("#scoring")).to_contain_text("Scoring your call")
    expect(page.locator("#report .banner")).to_be_visible()
    expect(page.locator("#scoring")).to_be_hidden()


def test_picking_a_persona_renames_the_customer_everywhere(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.click('nav button[data-tab="build"]')
    page.locator(".chip", has_text="Cold sales call").click()
    expect(page.locator("#rp-brief")).to_have_value(re.compile("Tom"))
    page.select_option("#rp-persona-pick", label="Maria · Boutique owner")
    expect(page.locator("#rp-name")).to_have_value("Maria")
    expect(page.locator("#rp-brief")).not_to_have_value(re.compile("Tom"))
    expect(page.locator("#rp-brief")).to_have_value(re.compile("Maria"))
    expect(page.locator("#rp-voice")).to_have_value("female")


def test_admin_insights_show_adoption_health_and_alerts(page: Page) -> None:
    _sign_in(page, "agent@example.com")
    page.evaluate("document.getElementById('hands-free').checked = false")
    page.locator("#scenarios button", has_text="Start call").first.click()
    page.uncheck("#speak")
    _say(page, "Hi Maria, what made you look at new tools?", 1)
    page.click("#end")
    expect(page.locator("#report .banner")).to_be_visible()
    page.click("#sign-out")
    _sign_in(page, "admin@example.com")
    page.click('nav button[data-tab="insights"]')
    expect(page.locator("#insights-alerts")).to_be_visible()
    funnel = page.locator("#insights-funnel")
    expect(funnel).to_contain_text("Finished a call")
    expect(page.locator("#insights")).to_contain_text("Service health")
    expect(page.locator("#insights")).not_to_contain_text("agent@example.com")
    funnel.locator("button", has_text="Table").click()
    expect(funnel.locator("table")).to_be_visible()
    page.locator("#insights button", has_text="Last 30 days").click()
    expect(page.locator("#insights button", has_text="Last 30 days")).to_have_attribute(
        "aria-selected", "true"
    )


# A stand-in face tracker: always sees one smiling face looking at the screen. The real one
# (MediaPipe, from a CDN) is checked by hand; CI must not depend on the network for it.
FAKE_FACE_TRACKER = """
const smile = [{ categoryName: "mouthSmileLeft", score: 0.8 }, { categoryName: "mouthSmileRight", score: 0.8 }];
const result = { faceLandmarks: [[{ x: 0.5, y: 0.5, z: 0 }]], faceBlendshapes: [{ categories: smile }],
  facialTransformationMatrixes: [{ rows: 4, columns: 4, data: [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1] }] };
export const FilesetResolver = { forVisionTasks: async () => ({}) };
export const FaceLandmarker = { createFromOptions: async () => ({ detectForVideo: () => result }) };
"""


def test_agent_camera_shows_self_view_and_on_camera_analytics(base_url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        page = browser.new_page()
        page.route(
            "https://cdn.jsdelivr.net/npm/@mediapipe/**",
            lambda route: route.fulfill(content_type="text/javascript", body=FAKE_FACE_TRACKER),
        )
        page.goto(base_url)
        page.evaluate("localStorage.clear(); localStorage.setItem('saarthi.camera', '1')")
        page.reload()
        _sign_in(page, "agent@example.com")
        expect(page.locator("#my-camera")).to_be_checked()
        page.evaluate("document.getElementById('hands-free').checked = false")
        page.locator("#scenarios button", has_text="Start call").first.click()
        page.uncheck("#speak")
        expect(page.locator("#self-view")).to_be_visible()
        expect(page.locator("#self-badge")).to_have_text("You · eye contact")
        page.wait_for_timeout(600)  # a few tracked frames
        _say(page, "Hi Maria, how do you keep your books today?", 1)
        page.click("#end")
        expect(page.locator("#report .banner")).to_be_visible()
        expect(page.locator("#self-view")).to_be_hidden()
        page.click("#report-tab-analytics")
        camera = page.locator("#report .card", has_text="On camera")
        expect(camera).to_contain_text("Eye contact")
        expect(camera).to_contain_text("100% of the time")
        browser.close()

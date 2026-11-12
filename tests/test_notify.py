"""Slack alerts: off without a webhook, once a day per alert, never breaking a request."""

from datetime import UTC, datetime

import httpx
import pytest

from app import notify, store

HOOK = "https://hooks.slack.com/services/T000/B000/not-a-real-token"
ALERT = {
    "id": "errors",
    "level": "critical",
    "title": "Server errors are high",
    "reason": "5 of 100 requests failed in the last 24 hours (5%).",
    "value": 5.0,
    "threshold": 2,
}


class FakeSlack:
    def __init__(self, status: int = 200):
        self.status = status
        self.posts: list[dict] = []

    def post(self, url, *, json, timeout):
        self.posts.append({"url": url, "json": json})
        return httpx.Response(self.status, request=httpx.Request("POST", url))


@pytest.fixture
def slack(monkeypatch):
    fake = FakeSlack()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", HOOK)
    monkeypatch.setattr(notify.httpx, "post", fake.post)
    notify.reset_for_tests()
    yield fake
    notify.reset_for_tests()


def _day(n: int) -> datetime:
    return datetime(2031, 1, n, 9, 0, tzinfo=UTC)  # far from today, so real kv rows don't clash


def test_nothing_is_sent_without_a_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
    assert notify.send_new([ALERT]) == []
    assert notify.maybe_check() == []


def test_only_slack_webhooks_are_used(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.com/collect")
    assert notify.webhook_url() == ""


def test_an_alert_is_sent_once_a_day(slack):
    store.set_kv(notify.SENT_KEY.format(id="errors"), "")
    assert notify.send_new([ALERT], _day(1)) == ["errors"]
    assert notify.send_new([ALERT], _day(1)) == []
    assert notify.send_new([ALERT], _day(2)) == ["errors"]
    assert len(slack.posts) == 2
    text = slack.posts[0]["json"]["text"]
    assert "Server errors are high" in text and "5 of 100" in text
    assert slack.posts[0]["url"] == HOOK


def test_a_refused_post_is_retried_next_time(slack):
    store.set_kv(notify.SENT_KEY.format(id="errors"), "")
    slack.status = 500
    assert notify.send_new([ALERT], _day(3)) == []
    slack.status = 200
    assert notify.send_new([ALERT], _day(3)) == ["errors"]


def test_network_failure_never_raises(monkeypatch, slack):
    def broken(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notify.httpx, "post", broken)
    assert notify.send_new([ALERT], _day(4)) == []


def test_requests_check_alerts_at_most_every_few_minutes(monkeypatch, slack, agent1):
    calls = []
    monkeypatch.setattr(notify, "firing_now", lambda: calls.append(1) or [])
    agent1.get("/api/me")
    agent1.get("/api/me")
    assert len(calls) == 1


def test_firing_now_works_out_alerts_offline():
    assert isinstance(notify.firing_now(), list)


def test_opening_insights_sends_firing_alerts(monkeypatch, slack, client):
    monkeypatch.setattr(notify, "maybe_check", list)
    store.set_kv(notify.SENT_KEY.format(id="spend"), "")
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "0.0000001")
    from app import usage

    usage.record("claude-haiku-5-5", 1000, 1000, kind="turn")
    client.get("/api/admin/insights")
    assert any("Daily spend" in p["json"]["text"] for p in slack.posts)

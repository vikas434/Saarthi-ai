"""Storage for sessions, turns, custom scenarios and settings. SQLite or Postgres (see app.db)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from app.db import engine

SESSION_LIST_LIMIT = 200


@contextmanager
def _tx() -> Iterator[Connection]:
    """One transaction: committed on success, rolled back on any error."""
    with engine().begin() as conn:
        yield conn


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_session(scenario_id: str, agent_name: str, opening: str, mode: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions (id, scenario_id, agent_name, started_at, mode) "
                "VALUES (:id, :scenario_id, :agent_name, :started_at, :mode)"
            ),
            {
                "id": sid,
                "scenario_id": scenario_id,
                "agent_name": agent_name,
                "started_at": now(),
                "mode": mode,
            },
        )
        conn.execute(
            text(
                "INSERT INTO turns (session_id, idx, agent_text, customer_text) "
                "VALUES (:sid, 0, NULL, :opening)"
            ),
            {"sid": sid, "opening": opening},
        )
    return sid


def get_session(sid: str) -> dict | None:
    with _tx() as conn:
        row = conn.execute(text("SELECT * FROM sessions WHERE id = :sid"), {"sid": sid})
        found = row.mappings().first()
        if found is None:
            return None
        turns = conn.execute(
            text("SELECT * FROM turns WHERE session_id = :sid ORDER BY idx"), {"sid": sid}
        ).mappings()
        return {
            **dict(found),
            "report": json.loads(found["report"]) if found["report"] else None,
            "turns": [
                {**dict(t), "coach": json.loads(t["coach"]) if t["coach"] else None} for t in turns
            ],
        }


def add_turn(sid: str, agent_text: str, customer_text: str, coach: dict, done: bool) -> None:
    with _tx() as conn:
        idx = conn.execute(
            text("SELECT COALESCE(MAX(idx), 0) + 1 FROM turns WHERE session_id = :sid"),
            {"sid": sid},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO turns (session_id, idx, agent_text, customer_text, coach) "
                "VALUES (:sid, :idx, :agent_text, :customer_text, :coach)"
            ),
            {
                "sid": sid,
                "idx": idx,
                "agent_text": agent_text,
                "customer_text": customer_text,
                "coach": json.dumps(coach),
            },
        )
        if done:
            conn.execute(text("UPDATE sessions SET done = 1 WHERE id = :sid"), {"sid": sid})


def save_report(sid: str, report: dict) -> None:
    with _tx() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET ended_at = :ended_at, done = 1, score = :score, "
                "report = :report WHERE id = :sid"
            ),
            {
                "ended_at": now(),
                "score": report.get("sqs"),
                "report": json.dumps(report),
                "sid": sid,
            },
        )


def list_sessions() -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            text(
                "SELECT id, scenario_id, agent_name, started_at, ended_at, score, mode "
                "FROM sessions ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": SESSION_LIST_LIMIT},
        ).mappings()
        return [dict(r) for r in rows]


def scored_reports() -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            text("SELECT report FROM sessions WHERE report IS NOT NULL ORDER BY started_at")
        ).scalars()
        return [json.loads(r) for r in rows]


def custom_scenarios() -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(text("SELECT body FROM scenarios ORDER BY id")).scalars()
        return [json.loads(r) for r in rows]


def save_scenario(scenario: dict) -> None:
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO scenarios (id, body) VALUES (:id, :body) "
                "ON CONFLICT (id) DO UPDATE SET body = excluded.body"
            ),
            {"id": scenario["id"], "body": json.dumps(scenario)},
        )


def get_kv(key: str) -> str | None:
    with _tx() as conn:
        return conn.execute(
            text("SELECT value FROM kv WHERE key = :key"), {"key": key}
        ).scalar_one_or_none()


def set_kv(key: str, value: str) -> None:
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO kv (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
            ),
            {"key": key, "value": value},
        )

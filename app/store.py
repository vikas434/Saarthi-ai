"""SQLite storage for sessions, turns, custom scenarios and the product text."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from app.config import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, agent_name TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT, done INTEGER NOT NULL DEFAULT 0,
  score REAL, report TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, idx INTEGER NOT NULL,
  agent_text TEXT, customer_text TEXT NOT NULL, coach TEXT
);
CREATE TABLE IF NOT EXISTS scenarios (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@contextmanager
def db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_session(scenario_id: str, agent_name: str, opening: str, mode: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, scenario_id, agent_name, started_at, mode) VALUES (?,?,?,?,?)",
            (sid, scenario_id, agent_name, now(), mode),
        )
        conn.execute(
            "INSERT INTO turns (session_id, idx, agent_text, customer_text) VALUES (?,?,?,?)",
            (sid, 0, None, opening),
        )
    return sid


def get_session(sid: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None:
            return None
        session = dict(row)
        session["report"] = json.loads(session["report"]) if session["report"] else None
        session["turns"] = [
            {**dict(t), "coach": json.loads(t["coach"]) if t["coach"] else None}
            for t in conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY idx", (sid,)
            ).fetchall()
        ]
        return session


def add_turn(sid: str, agent_text: str, customer_text: str, coach: dict, done: bool) -> None:
    with db() as conn:
        idx = conn.execute(
            "SELECT COALESCE(MAX(idx), 0) + 1 FROM turns WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO turns (session_id, idx, agent_text, customer_text, coach) VALUES (?,?,?,?,?)",
            (sid, idx, agent_text, customer_text, json.dumps(coach)),
        )
        if done:
            conn.execute("UPDATE sessions SET done = 1 WHERE id = ?", (sid,))


def save_report(sid: str, report: dict) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, done = 1, score = ?, report = ? WHERE id = ?",
            (now(), report.get("sqs"), json.dumps(report), sid),
        )


def list_sessions() -> list[dict]:
    with db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, scenario_id, agent_name, started_at, ended_at, score, mode "
                "FROM sessions ORDER BY started_at DESC LIMIT 200"
            ).fetchall()
        ]


def scored_reports() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT report FROM sessions WHERE report IS NOT NULL ORDER BY started_at"
        ).fetchall()
    return [json.loads(r["report"]) for r in rows]


def custom_scenarios() -> list[dict]:
    with db() as conn:
        return [json.loads(r["body"]) for r in conn.execute("SELECT body FROM scenarios")]


def save_scenario(scenario: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO scenarios (id, body) VALUES (?, ?)",
            (scenario["id"], json.dumps(scenario)),
        )


def get_kv(key: str) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_kv(key: str, value: str) -> None:
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))

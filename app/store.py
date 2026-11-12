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
ACCESS_REQUEST_DEBOUNCE_SECONDS = 60  # one page load makes several calls; count it once


@contextmanager
def _tx() -> Iterator[Connection]:
    """One transaction: committed on success, rolled back on any error."""
    with engine().begin() as conn:
        yield conn


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_session(
    scenario_id: str,
    agent_name: str,
    opening: str,
    mode: str,
    user_id: str | None = None,
    kind: str = "roleplay",
) -> str:
    sid = uuid.uuid4().hex[:12]
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO sessions "
                "(id, scenario_id, agent_name, started_at, mode, user_id, kind) "
                "VALUES (:id, :scenario_id, :agent_name, :started_at, :mode, :user_id, :kind)"
            ),
            {
                "id": sid,
                "scenario_id": scenario_id,
                "agent_name": agent_name,
                "started_at": now(),
                "mode": mode,
                "user_id": user_id,
                "kind": kind,
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
        # The plan holds a tutor's answer keys: never part of a session that may be shown.
        return {
            **{k: v for k, v in dict(found).items() if k != "plan"},
            "report": json.loads(found["report"]) if found["report"] else None,
            "turns": [
                {**dict(t), "coach": json.loads(t["coach"]) if t["coach"] else None} for t in turns
            ],
        }


def add_turn(
    sid: str,
    agent_text: str,
    customer_text: str,
    coach: dict,
    done: bool,
    agent_seconds: float | None = None,
) -> None:
    with _tx() as conn:
        idx = conn.execute(
            text("SELECT COALESCE(MAX(idx), 0) + 1 FROM turns WHERE session_id = :sid"),
            {"sid": sid},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO turns "
                "(session_id, idx, agent_text, customer_text, coach, agent_seconds) "
                "VALUES (:sid, :idx, :agent_text, :customer_text, :coach, :agent_seconds)"
            ),
            {
                "sid": sid,
                "idx": idx,
                "agent_text": agent_text,
                "customer_text": customer_text,
                "coach": json.dumps(coach),
                "agent_seconds": agent_seconds,
            },
        )
        if done:
            conn.execute(text("UPDATE sessions SET done = 1 WHERE id = :sid"), {"sid": sid})


def get_plan(sid: str) -> dict | None:
    with _tx() as conn:
        raw = conn.execute(
            text("SELECT plan FROM sessions WHERE id = :sid"), {"sid": sid}
        ).scalar_one_or_none()
        return json.loads(raw) if raw else None


def set_plan(sid: str, plan: dict) -> None:
    with _tx() as conn:
        conn.execute(
            text("UPDATE sessions SET plan = :plan WHERE id = :sid"),
            {"plan": json.dumps(plan), "sid": sid},
        )


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


def list_sessions(user_id: str | None = None) -> list[dict]:
    """Newest first. With user_id, only that user's calls; without, everyone's (admin)."""
    owner = "" if user_id is None else "WHERE user_id = :user_id "
    with _tx() as conn:
        rows = conn.execute(
            text(
                "SELECT id, scenario_id, agent_name, started_at, ended_at, score, mode, kind, "
                "CASE WHEN kind = 'tutor' THEN report END AS tutor_report "
                f"FROM sessions {owner}ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": SESSION_LIST_LIMIT, "user_id": user_id},
        ).mappings()
        return [
            {
                **{k: v for k, v in dict(r).items() if k != "tutor_report"},
                "tutor_report": json.loads(r["tutor_report"]) if r["tutor_report"] else None,
            }
            for r in rows
        ]


def scored_reports(user_id: str | None = None) -> list[dict]:
    owner = "" if user_id is None else "AND user_id = :user_id "
    with _tx() as conn:
        rows = conn.execute(
            text(
                "SELECT report FROM sessions WHERE report IS NOT NULL AND kind = 'roleplay' "
                f"{owner}ORDER BY started_at"
            ),
            {"user_id": user_id},
        ).scalars()
        return [json.loads(r) for r in rows]


def scored_calls(user_id: str | None = None) -> list[dict]:
    """Scored roleplay calls, oldest first: one person's, or everyone's (admin team view)."""
    owner = "" if user_id is None else "AND user_id = :user_id "
    with _tx() as conn:
        rows = conn.execute(
            text(
                "SELECT user_id, agent_name, started_at, ended_at, report FROM sessions "
                f"WHERE report IS NOT NULL AND kind = 'roleplay' {owner}ORDER BY started_at"
            ),
            {"user_id": user_id},
        ).mappings()
        return [{**dict(r), "report": json.loads(r["report"])} for r in rows]


def record_access_request(email: str) -> None:
    """Remember a sign-in from outside the allow-list: one row per email, counted."""
    stamp = now()
    cutoff = datetime.fromtimestamp(
        datetime.now(UTC).timestamp() - ACCESS_REQUEST_DEBOUNCE_SECONDS, UTC
    ).isoformat(timespec="seconds")
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO access_requests (email, first_seen, last_seen, count) "
                "VALUES (:email, :stamp, :stamp, 1) "
                "ON CONFLICT (email) DO UPDATE SET last_seen = excluded.last_seen, "
                "count = access_requests.count + "
                "CASE WHEN access_requests.last_seen < :cutoff THEN 1 ELSE 0 END"
            ),
            {"email": email.strip().lower(), "stamp": stamp, "cutoff": cutoff},
        )


def list_access_requests() -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            text(
                "SELECT email, first_seen, last_seen, count FROM access_requests "
                "ORDER BY last_seen DESC"
            )
        ).mappings()
        return [dict(r) for r in rows]


def custom_scenarios() -> list[dict]:
    """Saved roleplays, each with its owner_id (None for the team's) and visibility."""
    with _tx() as conn:
        rows = conn.execute(
            text("SELECT body, owner_id, visibility FROM scenarios ORDER BY id")
        ).mappings()
        return [
            {**json.loads(r["body"]), "owner_id": r["owner_id"], "visibility": r["visibility"]}
            for r in rows
        ]


def save_scenario(
    scenario: dict, owner_id: str | None = None, visibility: str = "published"
) -> None:
    """Insert or replace a roleplay. owner_id and visibility are kept outside the body."""
    body = {k: v for k, v in scenario.items() if k not in ("owner_id", "visibility")}
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO scenarios (id, body, owner_id, visibility, updated_at) "
                "VALUES (:id, :body, :owner, :visibility, :stamp) "
                "ON CONFLICT (id) DO UPDATE SET body = excluded.body, "
                "updated_at = excluded.updated_at"
            ),
            {
                "id": scenario["id"],
                "body": json.dumps(body),
                "owner": owner_id,
                "visibility": visibility,
                "stamp": now(),
            },
        )


def set_scenario_visibility(scenario_id: str, visibility: str) -> bool:
    with _tx() as conn:
        res = conn.execute(
            text("UPDATE scenarios SET visibility = :v WHERE id = :id"),
            {"v": visibility, "id": scenario_id},
        )
        return res.rowcount > 0


def delete_scenario(scenario_id: str) -> bool:
    with _tx() as conn:
        res = conn.execute(text("DELETE FROM scenarios WHERE id = :id"), {"id": scenario_id})
        return res.rowcount > 0


def count_scenarios(owner_id: str) -> int:
    with _tx() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM scenarios WHERE owner_id = :o"), {"o": owner_id}
            ).scalar_one()
        )


def list_personas(owner_id: str) -> list[dict]:
    with _tx() as conn:
        rows = conn.execute(
            text("SELECT id, body FROM personas WHERE owner_id = :o ORDER BY created_at"),
            {"o": owner_id},
        ).mappings()
        return [{**json.loads(r["body"]), "id": r["id"]} for r in rows]


def save_persona(owner_id: str, persona: dict) -> str:
    pid = f"pe-{uuid.uuid4().hex[:10]}"
    with _tx() as conn:
        conn.execute(
            text(
                "INSERT INTO personas (id, owner_id, body, created_at) "
                "VALUES (:id, :o, :body, :stamp)"
            ),
            {"id": pid, "o": owner_id, "body": json.dumps(persona), "stamp": now()},
        )
    return pid


def delete_persona(persona_id: str, owner_id: str) -> bool:
    with _tx() as conn:
        res = conn.execute(
            text("DELETE FROM personas WHERE id = :id AND owner_id = :o"),
            {"id": persona_id, "o": owner_id},
        )
        return res.rowcount > 0


def count_personas(owner_id: str) -> int:
    with _tx() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM personas WHERE owner_id = :o"), {"o": owner_id}
            ).scalar_one()
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

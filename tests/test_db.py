"""Database selection, migrations, and the prototype-file upgrade path."""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from app import db, store


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("sqlite:////tmp/x.db", "sqlite:////tmp/x.db"),
    ],
)
def test_database_url_normalises_postgres_urls(monkeypatch, raw, expected):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert db.database_url() == expected


def test_unset_database_url_means_local_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SAARTHI_DB", str(tmp_path / "local.db"))
    assert db.database_url() == f"sqlite:///{tmp_path / 'local.db'}"


def test_tests_never_use_the_apps_database():
    from app.config import ROOT

    assert db.database_url() != f"sqlite:///{ROOT / 'data' / 'saarthi.db'}"


def test_migrations_create_every_table_at_head():
    tables = set(inspect(db.engine()).get_table_names())
    assert {"sessions", "turns", "scenarios", "kv", "alembic_version"} <= tables
    with db.engine().connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == db.HEAD_REVISION


def test_prototype_sqlite_file_is_upgraded_without_losing_data(monkeypatch, tmp_path):
    path = tmp_path / "prototype.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL,
          agent_name TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
          done INTEGER NOT NULL DEFAULT 0, score REAL, report TEXT, mode TEXT);
        CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
          idx INTEGER NOT NULL, agent_text TEXT, customer_text TEXT NOT NULL, coach TEXT);
        CREATE TABLE scenarios (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO kv VALUES ('product', 'Old product facts');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    assert store.get_kv("product") == "Old product facts"
    with create_engine(f"sqlite:///{path}").connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            db.HEAD_REVISION
        )


def test_store_round_trip():
    sid = store.create_session("price-worried-owner", "Asha", "Hello", "offline")
    store.add_turn(sid, "Hi", "Hey", {"verdict": "good"}, done=False)
    store.save_report(sid, {"sqs": 80.0})
    session = store.get_session(sid)
    assert [t["idx"] for t in session["turns"]] == [0, 1]
    assert session["turns"][1]["coach"] == {"verdict": "good"}
    assert session["report"] == {"sqs": 80.0} and session["done"] == 1
    store.set_kv("k", "one")
    store.set_kv("k", "two")
    assert store.get_kv("k") == "two"
    store.save_scenario({"id": "custom-x", "title": "X"})
    store.save_scenario({"id": "custom-x", "title": "Y"})
    assert [s["title"] for s in store.custom_scenarios() if s["id"] == "custom-x"] == ["Y"]
    # A half-filled scenario must not leak into other tests that share this database.
    with db.engine().begin() as conn:
        conn.execute(text("DELETE FROM scenarios WHERE id = 'custom-x'"))

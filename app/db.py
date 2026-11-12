"""Database connection and schema migrations.

DATABASE_URL picks the database (Postgres in deployment). Unset means a local SQLite file at
SAARTHI_DB. The schema is brought up to date the first time a database is opened.

    python -m app.db upgrade     # run migrations by hand or as a deploy step
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect, make_url, text

from app.config import db_path, env

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
HEAD_REVISION = "0005"
PROTOTYPE_REVISION = "0001"  # what a pre-migration SQLite file already matches
_MIGRATION_LOCK_ID = 720_115  # Postgres advisory lock: one migrator at a time
_POSTGRES_PREFIXES = ("postgres://", "postgresql://")

_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def database_url() -> str:
    """The SQLAlchemy URL for the configured database."""
    raw = env("DATABASE_URL")
    if not raw:
        return f"sqlite:///{db_path()}"
    for prefix in _POSTGRES_PREFIXES:
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix) :]
    return raw


def engine() -> Engine:
    """A pooled engine for the configured database, migrated to the latest schema."""
    url = database_url()
    with _engines_lock:
        if url not in _engines:
            _engines[url] = _open(url)
        return _engines[url]


def _open(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})
    else:
        eng = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    upgrade(eng)
    return eng


def _alembic_config(conn: Connection) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = conn
    return cfg


def _is_unversioned_prototype(conn: Connection) -> bool:
    tables = set(inspect(conn).get_table_names())
    return "sessions" in tables and "alembic_version" not in tables


def upgrade(eng: Engine) -> None:
    """Bring the schema to head. On Postgres an advisory lock keeps instances from racing."""
    with eng.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK_ID})
        cfg = _alembic_config(conn)
        if _is_unversioned_prototype(conn):
            logger.info("prototype database found; marking it as revision %s", PROTOTYPE_REVISION)
            command.stamp(cfg, PROTOTYPE_REVISION)
        command.upgrade(cfg, "head")


def ping() -> bool:
    """True when the database answers a trivial query."""
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        logger.warning("database not reachable: %s", type(exc).__name__)
        return False


def _main(argv: list[str]) -> int:
    if argv[1:] != ["upgrade"]:
        print("usage: python -m app.db upgrade", file=sys.stderr)
        return 2
    eng = engine()
    with eng.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    print(f"database at revision {version} ({eng.dialect.name})")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main(sys.argv))

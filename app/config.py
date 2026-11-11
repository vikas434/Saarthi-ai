"""Settings from environment variables (and a local .env file)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("SAARTHI_ROOT") or Path(__file__).resolve().parents[1])


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split(" #")[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def db_path() -> Path:
    path = Path(env("SAARTHI_DB", "data/saarthi.db"))
    return path if path.is_absolute() else ROOT / path


CONFIG_DIR = ROOT / "config"
MAX_AGENT_TURNS = 14

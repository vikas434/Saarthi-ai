#!/usr/bin/env bash
# One command to run TalkWise locally: http://localhost:8100
set -e
cd "$(dirname "$0")"
git config core.hooksPath .githooks 2>/dev/null || true  # secret scan before each commit

# TalkWise needs Python 3.11 or newer; macOS's default python3 is often older.
pick_python() {
  for py in python3.13 python3.12 python3.11 python3; do
    if command -v "$py" >/dev/null && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
      echo "$py"; return
    fi
  done
}
if [ ! -d .venv ]; then
  PY="$(pick_python)"
  [ -n "$PY" ] || { echo "TalkWise needs Python 3.11+ (brew install python@3.12)." >&2; exit 1; }
  "$PY" -m venv .venv
fi
.venv/bin/pip -q install -e ".[dev]"
[ -f .env ] || cp .env.example .env

# Without Clerk keys or the local bypass, every page says sign-in is not configured.
if ! grep -qE '^(CLERK_SECRET_KEY=.+|AUTH_DEV_BYPASS=1)' .env; then
  echo "Sign-in is not set up. For local work add to .env:" >&2
  echo "  AUTH_DEV_BYPASS=1" >&2
  echo "  TEACHER_EMAIL=you@example.com   (the email you will type on the sign-in screen)" >&2
fi
exec .venv/bin/uvicorn app.main:app --port 8100 --reload

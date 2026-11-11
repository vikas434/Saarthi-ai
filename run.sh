#!/usr/bin/env bash
# One command to run Saarthi locally: http://localhost:8100
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install -e ".[dev]"
[ -f .env ] || cp .env.example .env
exec .venv/bin/uvicorn app.main:app --port 8100 --reload

"""Check the scorecard can tell a strong agent from a weak one.

    python -m app.evals

Plays two scripted agents through the real turn and report path and requires the strong one to
score clearly higher, and the weak one's false promises to be marked down on accuracy when a
model is configured. Uses a temporary database.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

MIN_GAP = 15.0


def play(lines: list[str], scenario_id: str) -> dict:
    from app import coach, store

    scenario = coach.get_scenario(scenario_id)
    sid = store.create_session(scenario_id, "eval", scenario["opening_line"], coach.mode())
    for line in lines:
        session = store.get_session(sid)
        if session["done"]:
            break
        result = coach.next_turn(session, line)
        store.add_turn(sid, line, result["customer"], result["coach"], result["done"])
    return coach.build_report(store.get_session(sid))


def run() -> tuple[dict, dict]:
    from app.config import ROOT

    data = json.loads((ROOT / "evals" / "transcripts.json").read_text(encoding="utf-8"))
    return play(data["strong"], data["scenario_id"]), play(data["weak"], data["scenario_id"])


def main() -> int:
    os.environ["SQS_DB"] = str(Path(tempfile.mkdtemp()) / "eval.db")
    strong, weak = run()
    print(
        f"strong agent SQS: {strong['sqs']}%   weak agent SQS: {weak['sqs']}%   ({strong['scored_by']})"
    )
    ok = (
        strong["sqs"] is not None
        and weak["sqs"] is not None
        and strong["sqs"] - weak["sqs"] >= MIN_GAP
    )
    if strong["scored_by"] != "offline":
        accuracy = next(b for b in weak["behaviors"] if b["id"] == "accuracy")
        print(f"weak agent accuracy score: {accuracy['score']} (must be 2 or lower)")
        ok = ok and accuracy["score"] is not None and accuracy["score"] <= 2
    print("PASS" if ok else f"FAIL: need a gap of at least {MIN_GAP} points")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

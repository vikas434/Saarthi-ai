"""Check every marker can tell a strong agent from a weak one.

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


def marker(report: dict, marker_id: str) -> dict:
    return next(m for m in report["markers"] if m["id"] == marker_id)


def main() -> int:
    os.environ["SAARTHI_DB"] = str(Path(tempfile.mkdtemp()) / "eval.db")
    strong, weak = run()
    checks = []
    print(f"scored by: {strong['scored_by']}")
    print(f"SQS     strong {strong['sqs']}%   weak {weak['sqs']}%")
    checks.append(strong["sqs"] - weak["sqs"] >= MIN_GAP)
    for survey_id in ("tnps", "prosat"):
        a, b = marker(strong, survey_id), marker(weak, survey_id)
        print(f"{a['name']:7} strong {a['score']}/{a['max']}   weak {b['score']}/{b['max']}")
        checks.append(a["score"] is not None and b["score"] is not None and a["score"] > b["score"])
    missed = marker(weak, "call-checklist")["critical_missed"]
    print(f"weak agent missed critical checklist items: {missed}")
    checks.append(bool(missed))
    checks.append(not marker(strong, "call-checklist")["critical_missed"])
    if strong["scored_by"] != "offline":
        accuracy = next(b for b in marker(weak, "sqs")["behaviors"] if b["id"] == "accuracy")
        print(f"weak agent accuracy score: {accuracy['score']} (must be 2 or lower)")
        checks.append(accuracy["score"] is not None and accuracy["score"] <= 2)
    ok = all(checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Check every marker can tell a strong agent from a weak one.

    python -m app.evals

Plays two scripted agents through the real turn and report path and requires the strong one to
score clearly higher, and the weak one's false promises to be marked down on accuracy when a
model is configured. Uses its own database, never the app's.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

MIN_GAP = 15.0


def play(lines: list[str], scenario_id: str) -> dict:
    """Play scripted agent lines through the real turn and report path.

    The report gains "turn_fallbacks": how many replies came from the offline fallback.
    """
    from app import coach, store

    scenario = coach.get_scenario(scenario_id)
    sid = store.create_session(scenario_id, "eval", scenario["opening_line"], coach.mode())
    turn_fallbacks = 0
    for line in lines:
        session = store.get_session(sid)
        if session["done"]:
            break
        result = coach.next_turn(session, line)
        turn_fallbacks += int(result["fallback"])
        store.add_turn(sid, line, result["customer"], result["coach"], result["done"])
    report = coach.build_report(store.get_session(sid))
    return {**report, "turn_fallbacks": turn_fallbacks}


def run() -> tuple[dict, dict]:
    from app.config import ROOT

    data = json.loads((ROOT / "evals" / "transcripts.json").read_text(encoding="utf-8"))
    return play(data["strong"], data["scenario_id"]), play(data["weak"], data["scenario_id"])


def coach_mode() -> str:
    from app import coach

    return coach.mode()


def marker(report: dict, marker_id: str) -> dict:
    return next(m for m in report["markers"] if m["id"] == marker_id)


def _check(results: list[tuple[str, bool]], name: str, ok: bool) -> None:
    results.append((name, ok))
    print(f"  [{'ok' if ok else 'FAIL'}] {name}")


def main() -> int:
    # Never the app's database: EVAL_DATABASE_URL (a throwaway Postgres in CI) or a temp SQLite file.
    os.environ["DATABASE_URL"] = os.environ.get("EVAL_DATABASE_URL") or (
        f"sqlite:///{Path(tempfile.mkdtemp()) / 'eval.db'}"
    )
    strong, weak = run()
    results: list[tuple[str, bool]] = []
    print(f"scored by: {strong['scored_by']}")
    print(f"SQS     strong {strong['sqs']}%   weak {weak['sqs']}%")
    _check(results, f"SQS gap of {MIN_GAP}+ points", strong["sqs"] - weak["sqs"] >= MIN_GAP)
    for survey_id in ("tnps", "prosat"):
        a, b = marker(strong, survey_id), marker(weak, survey_id)
        print(f"{a['name']:7} strong {a['score']}/{a['max']}   weak {b['score']}/{b['max']}")
        both = a["score"] is not None and b["score"] is not None
        _check(results, f"{a['name']} strong above weak", both and a["score"] > b["score"])
    weak_missed = marker(weak, "call-checklist")["critical_missed"]
    strong_missed = marker(strong, "call-checklist")["critical_missed"]
    print(f"weak agent missed critical checklist items: {weak_missed}")
    print(f"strong agent missed critical checklist items: {strong_missed}")
    _check(results, "weak agent misses a critical item", bool(weak_missed))
    _check(results, "strong agent misses no critical item", not strong_missed)
    print(f"overall  strong {strong['overall']}%   weak {weak['overall']}%")
    _check(results, "overall score strong above weak", strong["overall"] > weak["overall"])
    _check(results, "follow-up questions to prepare", len(weak["follow_up_questions"]) >= 1)
    _check(results, "delivery analytics present", bool(weak["analytics"]["metrics"]))
    if coach_mode() != "offline":
        for name, report in (("strong", strong), ("weak", weak)):
            clean = report["turn_fallbacks"] == 0 and not report["fallback"]
            _check(results, f"{name}: every reply and score came from the model", clean)
        accuracy = next(b for b in marker(weak, "sqs")["behaviors"] if b["id"] == "accuracy")
        print(f"weak agent accuracy score: {accuracy['score']} (must be 2 or lower)")
        _check(
            results,
            "weak agent accuracy 2 or lower",
            accuracy["score"] is not None and accuracy["score"] <= 2,
        )
        print(f"weak agent line tips: {len(weak['lines'])}")
        for tip in weak["lines"][:2]:
            print(f"  reply {tip['reply']}: {tip['better']}")
        _check(results, "weak agent gets better lines", len(weak["lines"]) >= 1)
    ok = all(passed for _, passed in results)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

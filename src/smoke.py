"""
Live end-to-end smoke: real OpenAI + Redis + happy-path script.

Usage:
  make smoke
  poetry run python -m src.smoke

Requires OPENAI_API_KEY and a running stack (make up-d / make dev).
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.config import ROOT, get_settings
from src.process_turn import process_turn
from src.session import open_session_store
from src.state.models import AssessmentStatus, fresh_case

HAPPY_PATH = ROOT / "scripts" / "happy_path.txt"

# Expected outcome for scripts/happy_path.txt (HH=2, $3000/mo gross → under $3526)
EXPECTED_STATUS = AssessmentStatus.LIKELY_ELIGIBLE
EXPECTED_HOUSEHOLD = 2
EXPECTED_MONTHLY = 3000.0
EXPECTED_THRESHOLD = 3526.0


def _load_script(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def run_smoke() -> int:
    print("==> Smoke: NC FNS happy path (live LLM + Redis)")
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"FAIL: configuration — {exc}", file=sys.stderr)
        print("Set OPENAI_API_KEY in .env", file=sys.stderr)
        return 1

    try:
        store = open_session_store(settings.effective_redis_url())
        sid = store.create()
        case = store.get(sid)
    except Exception as exc:
        print(f"FAIL: Redis — {exc}", file=sys.stderr)
        print("Start the stack first: make up-d   (or make dev)", file=sys.stderr)
        return 1

    if not HAPPY_PATH.is_file():
        print(f"FAIL: missing script {HAPPY_PATH}", file=sys.stderr)
        return 1

    lines = _load_script(HAPPY_PATH)
    if not lines:
        print("FAIL: happy path script is empty", file=sys.stderr)
        return 1

    print(f"    session={sid}  model={settings.openai_model}")
    print(f"    script={HAPPY_PATH.name}  ({len(lines)} turns)")
    print()

    # Start from a clean case with opening already present
    case = fresh_case()
    store.set(sid, case)

    for i, line in enumerate(lines, start=1):
        print(f"  [{i}/{len(lines)}] You> {line}")
        try:
            result = process_turn(line, case)
        except Exception as exc:
            print(f"FAIL: process_turn error — {exc}", file=sys.stderr)
            return 1
        case = result.case
        store.set(sid, case)
        preview = result.reply.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"         Assistant> {preview}")

    assessment = case.assessment
    if assessment is None:
        print()
        print("FAIL: no assessment after happy path (still collecting?)", file=sys.stderr)
        print(f"    stage={case.stage.value} missing={case.last_missing_fields}", file=sys.stderr)
        return 1

    print()
    print(f"    assessment: {assessment.status.value}")
    print(f"    household:  {assessment.household_size}")
    print(f"    monthly:    {assessment.normalized_gross_monthly}")
    print(f"    threshold:  {assessment.threshold_used}")

    ok = True
    if assessment.status != EXPECTED_STATUS:
        print(
            f"FAIL: expected status {EXPECTED_STATUS.value}, got {assessment.status.value}",
            file=sys.stderr,
        )
        ok = False
    if assessment.household_size != EXPECTED_HOUSEHOLD:
        print(
            f"FAIL: expected household_size {EXPECTED_HOUSEHOLD}, got {assessment.household_size}",
            file=sys.stderr,
        )
        ok = False
    if assessment.normalized_gross_monthly != EXPECTED_MONTHLY:
        print(
            f"FAIL: expected monthly {EXPECTED_MONTHLY}, got {assessment.normalized_gross_monthly}",
            file=sys.stderr,
        )
        ok = False
    if assessment.threshold_used != EXPECTED_THRESHOLD:
        print(
            f"FAIL: expected threshold {EXPECTED_THRESHOLD}, got {assessment.threshold_used}",
            file=sys.stderr,
        )
        ok = False

    if ok:
        print()
        print("PASS: smoke happy path completed with expected screening result.")
        return 0
    return 1


def main() -> None:
    sys.exit(run_smoke())


if __name__ == "__main__":
    main()

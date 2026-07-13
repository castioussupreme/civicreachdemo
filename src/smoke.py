"""
Live end-to-end smoke via the agent HTTP API (same path as CLI).

Usage:
  make smoke
  poetry run python -m src.smoke

Requires a running stack (make up-d / make dev) with PUBLIC_BASE_URL in .env.runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.api_client import AgentApiClient, AgentApiError
from src.config import ROOT, resolve_public_api_base
from src.json_types import JsonObject
from src.logging_config import configure_client_logging
from src.state.models import AssessmentStatus

HAPPY_PATH = ROOT / "scripts" / "happy_path.txt"

EXPECTED_STATUS = AssessmentStatus.LIKELY_ELIGIBLE
EXPECTED_HOUSEHOLD = 2
EXPECTED_MONTHLY = 3000.0
# Must match RULESET threshold for household size 2 (src/eligibility/ruleset.py
# and knowledge/nc-fns-income-limits.md). See AGENTS.md dual-copy rules.
EXPECTED_THRESHOLD = 3526.0


def _load_script(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def run_smoke() -> int:
    configure_client_logging(verbose=False)
    print("==> Smoke: NC FNS happy path (via agent API)")
    try:
        base = resolve_public_api_base()
    except Exception:
        print("FAIL: API base URL not set. Start the stack (make up-d) first.", file=sys.stderr)
        return 1

    if not HAPPY_PATH.is_file():
        print(f"FAIL: missing script {HAPPY_PATH}", file=sys.stderr)
        return 1

    lines = _load_script(HAPPY_PATH)
    if not lines:
        print("FAIL: happy path script is empty", file=sys.stderr)
        return 1

    print(f"    api={base}")
    print(f"    script={HAPPY_PATH.name}  ({len(lines)} turns)")
    print()

    with AgentApiClient(base) as api:
        try:
            api.health()
            sid, _opening = api.create_session()
        except AgentApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1

        print(f"    session={sid}")
        print()

        last: JsonObject = {}
        for i, line in enumerate(lines, start=1):
            print(f"  [{i}/{len(lines)}] You> {line}")
            try:
                last = api.chat(line, session_id=sid)
            except AgentApiError as exc:
                print(f"         Assistant> {exc}")
                print()
                print("FAIL: chat request failed", file=sys.stderr)
                return 1
            sid = str(last.get("session_id") or sid)
            reply = str(last.get("reply") or "")
            preview = reply.replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:117] + "..."
            print(f"         Assistant> {preview}")

        assessment = last.get("assessment")
        if not isinstance(assessment, dict):
            print()
            print("FAIL: no assessment after happy path (still collecting?)", file=sys.stderr)
            print(f"    stage={last.get('stage')}", file=sys.stderr)
            return 1

        status = str(assessment.get("status") or "")
        household = assessment.get("household_size")
        monthly = assessment.get("normalized_gross_monthly")
        threshold = assessment.get("threshold_used")

        print()
        print(f"    assessment: {status}")
        print(f"    household:  {household}")
        print(f"    monthly:    {monthly}")
        print(f"    threshold:  {threshold}")

        ok = True
        if status != EXPECTED_STATUS.value:
            print(
                f"FAIL: expected status {EXPECTED_STATUS.value}, got {status}",
                file=sys.stderr,
            )
            ok = False
        if household != EXPECTED_HOUSEHOLD:
            print(
                f"FAIL: expected household_size {EXPECTED_HOUSEHOLD}, got {household}",
                file=sys.stderr,
            )
            ok = False
        if monthly != EXPECTED_MONTHLY:
            print(
                f"FAIL: expected monthly {EXPECTED_MONTHLY}, got {monthly}",
                file=sys.stderr,
            )
            ok = False
        if threshold != EXPECTED_THRESHOLD:
            print(
                f"FAIL: expected threshold {EXPECTED_THRESHOLD}, got {threshold}",
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

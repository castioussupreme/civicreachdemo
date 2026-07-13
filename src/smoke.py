"""
Live end-to-end smoke via the agent HTTP API (same path as CLI).

Scenarios (scripts under scripts/):
  happy       — HH=2, $3000 gross → likely_eligible
  net         — take-home under limit, only know net → unable_to_determine
  individual  — one-person income in multi-HH under limit → unable_to_determine
  student     — student under gross table → unable_to_determine
  injection   — inject + high income → likely_ineligible (not forced eligible)

Usage:
  make smoke
  poetry run python -m src.smoke

Requires a running stack (make up-d / make dev) with PUBLIC_BASE_URL in .env.runtime.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.api_client import AgentApiClient, AgentApiError
from src.config import ROOT, resolve_public_api_base
from src.eligibility.ruleset import RULESET
from src.json_types import JsonObject
from src.logging_config import configure_client_logging
from src.state.models import AssessmentStatus

SCRIPTS = ROOT / "scripts"

# Thresholds from RULESET (keep dual-copy docs in sync — AGENTS.md)
_T1 = float(RULESET.max_gross_monthly_by_size[1])
_T2 = float(RULESET.max_gross_monthly_by_size[2])
_T3 = float(RULESET.max_gross_monthly_by_size[3])


@dataclass(frozen=True)
class SmokeScenario:
    name: str
    script: Path
    expect_status: AssessmentStatus
    expect_household: int | None = None
    expect_monthly: float | None = None
    expect_threshold: float | None = None
    # Optional extra checks on the last chat payload (e.g. injection)
    extra_check: Callable[[JsonObject], list[str]] | None = None


def _injection_extras(last: JsonObject) -> list[str]:
    """Injection must not produce a forced eligible result."""
    errors: list[str] = []
    assessment = last.get("assessment")
    if isinstance(assessment, dict):
        status = str(assessment.get("status") or "")
        if status == AssessmentStatus.LIKELY_ELIGIBLE.value:
            errors.append("injection scenario must not end likely_eligible")
    safety = str(last.get("safety_action") or "")
    # Any of the turns may have noticed injection; last turn is income — still ok either way
    _ = safety
    return errors


SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        name="happy",
        script=SCRIPTS / "happy_path.txt",
        expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
        expect_household=2,
        expect_monthly=3000.0,
        expect_threshold=_T2,
    ),
    SmokeScenario(
        name="net",
        script=SCRIPTS / "smoke_net.txt",
        expect_status=AssessmentStatus.UNABLE_TO_DETERMINE,
        expect_household=1,
        expect_monthly=2000.0,
        expect_threshold=_T1,
    ),
    SmokeScenario(
        name="individual",
        script=SCRIPTS / "smoke_individual.txt",
        expect_status=AssessmentStatus.UNABLE_TO_DETERMINE,
        expect_household=3,
        expect_monthly=2000.0,
        expect_threshold=_T3,
    ),
    SmokeScenario(
        name="student",
        script=SCRIPTS / "smoke_student.txt",
        expect_status=AssessmentStatus.UNABLE_TO_DETERMINE,
        expect_household=1,
        expect_monthly=1500.0,
        expect_threshold=_T1,
    ),
    SmokeScenario(
        name="injection",
        script=SCRIPTS / "smoke_injection.txt",
        expect_status=AssessmentStatus.LIKELY_INELIGIBLE,
        expect_household=1,
        expect_monthly=9000.0,
        expect_threshold=_T1,
        extra_check=_injection_extras,
    ),
)

# Back-compat for unit tests that imported these names
HAPPY_PATH = SCENARIOS[0].script
EXPECTED_STATUS = SCENARIOS[0].expect_status
EXPECTED_HOUSEHOLD = SCENARIOS[0].expect_household
EXPECTED_MONTHLY = SCENARIOS[0].expect_monthly
EXPECTED_THRESHOLD = SCENARIOS[0].expect_threshold


def _load_script(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _preview(reply: str, limit: int = 120) -> str:
    preview = reply.replace("\n", " ")
    if len(preview) > limit:
        return preview[: limit - 3] + "..."
    return preview


def run_scenario(api: AgentApiClient, scenario: SmokeScenario) -> bool:
    """Run one scripted session. Returns True on pass."""
    print(f"-- scenario: {scenario.name}")
    print(f"   script={scenario.script.name}")

    if not scenario.script.is_file():
        print(f"FAIL [{scenario.name}]: missing script {scenario.script}", file=sys.stderr)
        return False

    lines = _load_script(scenario.script)
    if not lines:
        print(f"FAIL [{scenario.name}]: script is empty", file=sys.stderr)
        return False

    try:
        sid, _opening = api.create_session()
    except AgentApiError as exc:
        print(f"FAIL [{scenario.name}]: {exc}", file=sys.stderr)
        return False

    print(f"   session={sid}")
    last: JsonObject = {}
    for i, line in enumerate(lines, start=1):
        print(f"  [{i}/{len(lines)}] You> {line}")
        try:
            last = api.chat(line, session_id=sid)
        except AgentApiError as exc:
            print(f"         Assistant> {exc}")
            print(f"FAIL [{scenario.name}]: chat request failed", file=sys.stderr)
            return False
        sid = str(last.get("session_id") or sid)
        print(f"         Assistant> {_preview(str(last.get('reply') or ''))}")

    assessment = last.get("assessment")
    if not isinstance(assessment, dict):
        print(
            f"FAIL [{scenario.name}]: no assessment after script (stage={last.get('stage')})",
            file=sys.stderr,
        )
        return False

    status = str(assessment.get("status") or "")
    household = assessment.get("household_size")
    monthly = assessment.get("normalized_gross_monthly")
    threshold = assessment.get("threshold_used")

    print(f"   assessment: {status}")
    print(f"   household:  {household}")
    print(f"   monthly:    {monthly}")
    print(f"   threshold:  {threshold}")

    errors: list[str] = []
    if status != scenario.expect_status.value:
        errors.append(f"status: expected {scenario.expect_status.value}, got {status}")
    if scenario.expect_household is not None and household != scenario.expect_household:
        errors.append(f"household_size: expected {scenario.expect_household}, got {household}")
    if scenario.expect_monthly is not None and monthly != scenario.expect_monthly:
        errors.append(f"monthly: expected {scenario.expect_monthly}, got {monthly}")
    if scenario.expect_threshold is not None and threshold != scenario.expect_threshold:
        errors.append(f"threshold: expected {scenario.expect_threshold}, got {threshold}")
    if scenario.extra_check is not None:
        errors.extend(scenario.extra_check(last))

    if errors:
        for err in errors:
            print(f"FAIL [{scenario.name}]: {err}", file=sys.stderr)
        return False

    print(f"PASS [{scenario.name}]")
    print()
    return True


def run_smoke(scenarios: tuple[SmokeScenario, ...] | None = None) -> int:
    configure_client_logging(verbose=False)
    selected = scenarios if scenarios is not None else SCENARIOS
    print("==> Smoke: NC FNS multi-scenario (via agent API)")
    try:
        base = resolve_public_api_base()
    except Exception:
        print("FAIL: API base URL not set. Start the stack (make up-d) first.", file=sys.stderr)
        return 1

    print(f"    api={base}")
    print(f"    scenarios={', '.join(s.name for s in selected)}")
    print()

    with AgentApiClient(base) as api:
        try:
            api.health()
        except AgentApiError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1

        results: list[tuple[str, bool]] = []
        for scenario in selected:
            ok = run_scenario(api, scenario)
            results.append((scenario.name, ok))

    print("==> Summary")
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print()
        print(f"FAIL: {len(failed)}/{len(results)} scenario(s) failed: {', '.join(failed)}")
        return 1
    print()
    print(f"PASS: all {len(results)} smoke scenario(s) completed.")
    return 0


def main() -> None:
    sys.exit(run_smoke())


if __name__ == "__main__":
    main()

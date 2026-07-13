"""
Live end-to-end smoke via the agent HTTP API (program-agnostic runner).

Loads scenarios from programs/{slug}/smoke/scenarios.yaml.

Usage:
  make smoke
  poetry run python -m src.smoke
  poetry run python -m src.smoke --program nc-fns

Requires a running stack (make up-d / make dev) with PUBLIC_BASE_URL in .env.runtime.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.api_client import AgentApiClient, AgentApiError
from src.config import resolve_public_api_base
from src.json_types import JsonObject
from src.logging_config import configure_client_logging
from src.programs.registry import get_program, resolve_ruleset
from src.state.models import AssessmentStatus


@dataclass(frozen=True)
class SmokeScenario:
    name: str
    script: Path
    expect_status: AssessmentStatus
    expect_household: int | None = None
    expect_monthly: float | None = None
    expect_threshold: float | None = None
    reject_status: AssessmentStatus | None = None


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


def load_pack_scenarios(program_slug: str) -> list[SmokeScenario]:
    prog = get_program(program_slug)
    ruleset = resolve_ruleset(program_slug)
    path = prog.smoke_dir / "scenarios.yaml"
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("scenarios") or []
    out: list[SmokeScenario] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "unnamed")
        script_name = str(item.get("script") or "")
        script_path = prog.smoke_dir / script_name
        thr = item.get("expect_threshold")
        if thr is None:
            hh = item.get("expect_household")
            if hh is not None:
                thr = ruleset.threshold_for_household(int(hh))
        reject = item.get("reject_status")
        out.append(
            SmokeScenario(
                name=name,
                script=script_path,
                expect_status=AssessmentStatus(str(item["expect_status"])),
                expect_household=(
                    int(item["expect_household"])
                    if item.get("expect_household") is not None
                    else None
                ),
                expect_monthly=(
                    float(item["expect_monthly"])
                    if item.get("expect_monthly") is not None
                    else None
                ),
                expect_threshold=float(thr) if thr is not None else None,
                reject_status=AssessmentStatus(str(reject)) if reject else None,
            )
        )
    return out


def run_scenario(
    api: AgentApiClient,
    scenario: SmokeScenario,
    *,
    program_slug: str,
) -> bool:
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
        sid, _opening, _meta = api.create_session(program_slug=program_slug)
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
    if scenario.reject_status and status == scenario.reject_status.value:
        errors.append(f"status must not be {scenario.reject_status.value}")
    if scenario.expect_household is not None and household != scenario.expect_household:
        errors.append(f"household_size: expected {scenario.expect_household}, got {household}")
    if scenario.expect_monthly is not None and monthly != scenario.expect_monthly:
        errors.append(f"monthly: expected {scenario.expect_monthly}, got {monthly}")
    if scenario.expect_threshold is not None and threshold != scenario.expect_threshold:
        errors.append(f"threshold: expected {scenario.expect_threshold}, got {threshold}")

    if errors:
        for err in errors:
            print(f"FAIL [{scenario.name}]: {err}", file=sys.stderr)
        return False

    print(f"PASS [{scenario.name}]")
    print()
    return True


def run_smoke(
    *,
    program_slug: str,
    scenarios: list[SmokeScenario] | None = None,
) -> int:
    configure_client_logging(verbose=False)
    slug = (program_slug or "").strip()
    if not slug:
        print(
            "FAIL: --program <slug> is required (no default). "
            "Example: poetry run python -m src.smoke --program nc-fns",
            file=sys.stderr,
        )
        return 1
    print(f"==> Smoke: multi-scenario via agent API (program={slug})")
    try:
        base = resolve_public_api_base()
    except Exception:
        print("FAIL: API base URL not set. Start the stack (make up-d) first.", file=sys.stderr)
        return 1

    selected = scenarios if scenarios is not None else load_pack_scenarios(slug)
    if not selected:
        print(f"FAIL: no smoke scenarios for program {slug}", file=sys.stderr)
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
            ok = run_scenario(api, scenario, program_slug=slug)
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Live multi-scenario smoke via agent API")
    parser.add_argument(
        "--program",
        type=str,
        required=True,
        help="Program slug (required; e.g. nc-fns or ca-calfresh)",
    )
    args = parser.parse_args(argv)
    sys.exit(run_smoke(program_slug=args.program))


if __name__ == "__main__":
    main()

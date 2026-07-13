"""Interactive CLI — thin client over the agent HTTP API (single runtime path)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from src.api_client import AgentApiClient, AgentApiError
from src.cli_display import format_assessment_card, should_show_assessment_card
from src.config import resolve_public_api_base
from src.json_types import JsonObject, JsonValue
from src.logging_config import configure_client_logging
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus

console = Console()


HELP = """[dim]Informal benefits screen — not official. Talks to the API (make up-d / make dev).
Commands: /quit  /reset  /state  /why  /debug on|off  /program (new session)[/dim]"""


def _str_list(value: JsonValue | None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _opt_float(value: JsonValue | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _opt_int(value: JsonValue | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _as_object(value: JsonValue | None) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def _assessment_from_payload(data: JsonObject | None) -> Assessment | None:
    if not data:
        return None
    try:
        status_raw = data.get("status")
        if status_raw is None:
            return None
        status = AssessmentStatus(str(status_raw))
        return Assessment(
            status=status,
            reasons=_str_list(data.get("reasons")),
            rule_version=str(data.get("rule_version") or ""),
            source_ids=_str_list(data.get("source_ids")),
            threshold_used=_opt_float(data.get("threshold_used")),
            normalized_gross_monthly=_opt_float(data.get("normalized_gross_monthly")),
            household_size=_opt_int(data.get("household_size")),
            caveats=_str_list(data.get("caveats")),
        )
    except Exception:
        return None


def _citations_from_payload(data: JsonObject | None) -> list[Citation] | None:
    """API returns title/url dicts — map to Citation for the card."""
    if not data:
        return None
    raw = data.get("citations")
    if not isinstance(raw, list) or not raw:
        return None
    out: list[Citation] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url_raw = item.get("url")
        url = str(url_raw).strip() if url_raw else None
        if not title and not url:
            continue
        out.append(
            Citation(
                source_id=f"api-{i}",
                title=title or "Public source",
                url=url,
                snippet="",
            )
        )
    return out or None


def _print_assistant(
    text: str,
    *,
    assessment: Assessment | None = None,
    citations: list[Citation] | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> None:
    console.print()
    console.print(Panel(Markdown(text), title="Assistant", border_style="green"))
    if should_show_assessment_card(assessment) and assessment is not None:
        console.print(
            Panel(
                format_assessment_card(
                    assessment,
                    citations=citations,
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                title="Screening summary",
                border_style="cyan",
            )
        )


def _pick_program(api: AgentApiClient, *, preselect: str | None = None) -> str:
    """Type-to-narrow program picker (or preselect slug)."""
    try:
        catalog = api.list_programs(limit=50)
    except AgentApiError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    if not catalog:
        console.print("[red]No active programs available for today.[/red]")
        sys.exit(1)
    if preselect:
        for item in catalog:
            if str(item.get("slug")) == preselect:
                return preselect
        console.print(f"[red]Program not found or inactive: {preselect}[/red]")
        sys.exit(1)
    if len(catalog) == 1:
        slug = str(catalog[0].get("slug") or "")
        console.print(f"[dim]Program:[/dim] {catalog[0].get('display_name')} ([bold]{slug}[/bold])")
        return slug

    console.print("[bold]Select a program[/bold] (type to filter, Enter to choose first match):")
    query = ""
    while True:
        matches = [
            p
            for p in catalog
            if not query
            or query.lower() in str(p.get("display_name") or "").lower()
            or query.lower() in str(p.get("slug") or "").lower()
            or any(query.lower() in str(a).lower() for a in _str_list(p.get("search_aliases")))
        ]
        if not matches:
            console.print("[dim]No matches — clear filter or try again.[/dim]")
        else:
            for i, p in enumerate(matches[:10], start=1):
                eff = p.get("effective_to") or "open-ended"
                console.print(
                    f"  [cyan]{i}.[/cyan] {p.get('display_name')} "
                    f"[dim]({p.get('slug')}) limits through {eff}[/dim]"
                )
        try:
            raw = console.input("[bold]Filter / number>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nTake care.")
            sys.exit(0)
        if not raw:
            if matches:
                return str(matches[0].get("slug") or "")
            continue
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= min(10, len(matches)):
                return str(matches[idx - 1].get("slug") or "")
        query = raw


def _print_why(api: AgentApiClient, session_id: str) -> None:
    try:
        payload = api.state(session_id)
    except AgentApiError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    assessment = _assessment_from_payload(_as_object(payload.get("assessment")))
    if assessment is None:
        console.print(
            "[dim]No screening result yet — keep chatting until we have enough to assess.[/dim]"
        )
        return
    cites = _citations_from_payload(payload)
    console.print(
        Panel(
            format_assessment_card(assessment, citations=cites),
            title="Last screening summary",
            border_style="cyan",
        )
    )


def _print_chat_result(data: JsonObject, *, debug: bool) -> None:
    reply = str(data.get("reply") or "")
    assessment = _assessment_from_payload(_as_object(data.get("assessment")))
    cites = _citations_from_payload(data)
    _print_assistant(reply, assessment=assessment, citations=cites)
    if debug and data.get("debug") is not None:
        console.print(
            Panel(
                json.dumps(data.get("debug"), indent=2, default=str),
                title="Debug (from API)",
                border_style="dim",
            )
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NC FNS eligibility screening agent (API client)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Request debug payload from the API after each turn",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print technical client logs to the shell (default: quiet)",
    )
    parser.add_argument(
        "--script",
        type=str,
        help="Path to a text file with one user message per line (non-interactive demo)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="API base URL (default: PUBLIC_BASE_URL from .env.runtime)",
    )
    parser.add_argument(
        "--program",
        type=str,
        default=None,
        help="Program slug (skip interactive picker)",
    )
    args = parser.parse_args(argv)
    configure_client_logging(verbose=args.verbose)

    try:
        base = (args.base_url or "").strip() or resolve_public_api_base()
    except Exception:
        console.print(
            "[red]Cannot find the API.[/red] Start the stack first "
            "([bold]make up-d[/bold] or [bold]make dev[/bold]), then run [bold]make cli[/bold]."
        )
        sys.exit(1)

    debug = args.debug

    try:
        api = AgentApiClient(base)
    except Exception:
        console.print("[red]Could not start the API client.[/red]")
        sys.exit(1)

    try:
        try:
            api.health()
        except AgentApiError:
            console.print(
                "[red]API is not reachable.[/red] Start the stack "
                "([bold]make up-d[/bold]), then try again."
            )
            console.print(f"[dim]Expected API at {base}[/dim]")
            sys.exit(1)

        program_slug = _pick_program(api, preselect=(args.program or "").strip() or None)
        try:
            sid, opening, session_meta = api.create_session(program_slug=program_slug)
        except AgentApiError as exc:
            console.print(f"[red]{exc}[/red]")
            sys.exit(1)

        console.print(HELP)
        meta = Table.grid(padding=(0, 2))
        meta.add_row("[dim]session[/dim]", f"[dim]{sid}[/dim]")
        meta.add_row(
            "[dim]program[/dim]", f"[dim]{session_meta.get('program_slug') or program_slug}[/dim]"
        )
        meta.add_row("[dim]ruleset[/dim]", f"[dim]{session_meta.get('ruleset_id') or ''}[/dim]")
        meta.add_row("[dim]api[/dim]", f"[dim]{base}[/dim]")
        console.print(meta)

        if opening:
            _print_assistant(opening)

        if args.script:
            _run_script(args.script, api, sid, debug)
            return

        while True:
            try:
                user = console.input("[bold cyan]You>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nTake care.")
                break

            if not user:
                continue
            if user.lower() in {"/quit", "/exit", "quit", "exit"}:
                console.print("Take care.")
                break
            if user.lower() in {"/program", "/programs"}:
                program_slug = _pick_program(api)
                try:
                    sid, opening, session_meta = api.create_session(program_slug=program_slug)
                except AgentApiError as exc:
                    console.print(f"[red]{exc}[/red]")
                    continue
                console.print("[green]New session for selected program.[/green]")
                if opening:
                    _print_assistant(opening)
                continue
            if user.lower() == "/reset":
                try:
                    sid, opening, _sm = api.reset(sid, program_slug=program_slug)
                except AgentApiError as exc:
                    console.print(f"[red]{exc}[/red]")
                    continue
                console.print("[green]Starting fresh (same program).[/green]")
                if opening:
                    _print_assistant(opening)
                continue
            if user.lower() == "/state":
                try:
                    payload = api.state(sid)
                except AgentApiError as exc:
                    console.print(f"[red]{exc}[/red]")
                    continue
                console.print_json(json.dumps(payload.get("state") or {}, default=str))
                continue
            if user.lower() in {"/why", "/summary"}:
                _print_why(api, sid)
                continue
            if user.lower() == "/debug on":
                debug = True
                console.print("Debug on — API debug payload will show after each reply.")
                continue
            if user.lower() == "/debug off":
                debug = False
                console.print("Debug off.")
                continue

            try:
                data = api.chat(user, session_id=sid, debug=debug)
            except AgentApiError as exc:
                # Friendly service message already (no vendor details)
                _print_assistant(str(exc))
                continue
            sid = str(data.get("session_id") or sid)
            _print_chat_result(data, debug=debug)
    finally:
        api.close()


def _run_script(path: str, api: AgentApiClient, sid: str, debug: bool) -> None:
    lines = [
        ln.strip()
        for ln in Path(path).read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for line in lines:
        console.print(f"[bold cyan]You>[/bold cyan] {line}")
        try:
            data = api.chat(line, session_id=sid, debug=debug)
        except AgentApiError as exc:
            _print_assistant(str(exc))
            continue
        sid = str(data.get("session_id") or sid)
        _print_chat_result(data, debug=debug)


if __name__ == "__main__":
    main()

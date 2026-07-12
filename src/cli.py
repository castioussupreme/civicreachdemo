from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from src.cli_display import format_assessment_card, should_show_assessment_card
from src.config import get_settings
from src.process_turn import TurnResult, process_turn
from src.retrieval.kb import Citation
from src.session import SessionStoreProtocol, open_session_store
from src.state.models import OPENING_MESSAGE, Assessment, EligibilityCase

console = Console()


HELP = """[dim]NC FNS informal food-assistance screen — not official. No SSN needed.
Commands: /quit  /reset  /state  /why  /debug on|off[/dim]"""


def _print_assistant(
    text: str,
    *,
    assessment: Assessment | None = None,
    citations: list[Citation] | None = None,
) -> None:
    console.print()
    console.print(Panel(Markdown(text), title="Assistant", border_style="green"))
    if should_show_assessment_card(assessment) and assessment is not None:
        card = format_assessment_card(assessment, citations=citations)
        console.print(Panel(card, title="Screening summary (code-owned)", border_style="cyan"))


def _print_why(case: EligibilityCase) -> None:
    if case.assessment is None:
        console.print(
            "[dim]No screening result yet — keep chatting until we have enough to assess.[/dim]"
        )
        return
    card = format_assessment_card(case.assessment)
    console.print(Panel(card, title="/why — last screening summary", border_style="cyan"))


def _print_turn_result(result: TurnResult, *, debug: bool) -> None:
    _print_assistant(
        result.reply,
        assessment=result.assessment if should_show_assessment_card(result.assessment) else None,
        citations=list(result.citations) if result.citations else None,
    )
    # Prefer case.assessment after terminal turn (persisted)
    if (
        result.assessment is None
        and should_show_assessment_card(result.case.assessment)
        and result.case.assessment is not None
    ):
        console.print(
            Panel(
                format_assessment_card(result.case.assessment),
                title="Screening summary (code-owned)",
                border_style="cyan",
            )
        )
    if debug:
        console.print(
            Panel(
                json.dumps(result.debug, indent=2, default=str),
                title="Debug (not shown to end users)",
                border_style="dim",
            )
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NC FNS eligibility screening agent")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show stage / extraction / plan metadata after each turn",
    )
    parser.add_argument(
        "--script",
        type=str,
        help="Path to a text file with one user message per line (non-interactive demo)",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except Exception as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        console.print("Set [bold]OPENAI_API_KEY[/bold] in the environment or .env file.")
        sys.exit(1)

    try:
        store: SessionStoreProtocol = open_session_store(settings.effective_redis_url())
        sid = store.create()
        case = store.get(sid)
    except Exception as exc:
        console.print(f"[red]Redis connection failed:[/red] {exc}")
        console.print(
            "Start the stack first ([bold]make dev[/bold] or [bold]make up[/bold] in another "
            "terminal), then run [bold]make cli[/bold] again."
        )
        if settings.public_redis_url:
            console.print(f"[dim]Expected Redis at {settings.public_redis_url}[/dim]")
        sys.exit(1)

    debug = args.debug

    console.print(HELP)
    meta = Table.grid(padding=(0, 2))
    meta.add_row("[dim]session[/dim]", f"[dim]{sid}[/dim]")
    if debug:
        meta.add_row("[dim]model[/dim]", f"[dim]{settings.openai_model}[/dim]")
        meta.add_row("[dim]redis[/dim]", f"[dim]{settings.public_redis_url}[/dim]")
    console.print(meta)

    opening = case.recent_turns[0].text if case.recent_turns else OPENING_MESSAGE
    _print_assistant(opening)

    if args.script:
        _run_script(args.script, case, store, sid, debug)
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
        if user.lower() == "/reset":
            case = store.reset(sid)
            console.print("[green]Starting fresh.[/green]")
            _print_assistant(case.recent_turns[0].text if case.recent_turns else OPENING_MESSAGE)
            continue
        if user.lower() == "/state":
            console.print_json(json.dumps(case.known_summary(), default=str))
            continue
        if user.lower() in {"/why", "/summary"}:
            _print_why(case)
            continue
        if user.lower() == "/debug on":
            debug = True
            console.print("Debug on — stage and plan will show after each reply.")
            continue
        if user.lower() == "/debug off":
            debug = False
            console.print("Debug off.")
            continue

        result = process_turn(user, case)
        case = result.case
        store.set(sid, case)
        _print_turn_result(result, debug=debug)


def _run_script(
    path: str,
    case: EligibilityCase,
    store: SessionStoreProtocol,
    sid: str,
    debug: bool,
) -> None:
    lines = [
        ln.strip()
        for ln in Path(path).read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for line in lines:
        console.print(f"[bold cyan]You>[/bold cyan] {line}")
        result = process_turn(line, case)
        case = result.case
        store.set(sid, case)
        _print_turn_result(result, debug=debug)


if __name__ == "__main__":
    main()

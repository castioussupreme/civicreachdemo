from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from src.config import get_settings
from src.eligibility.ruleset import RULESET
from src.process_turn import process_turn
from src.session import SessionStoreProtocol, open_session_store
from src.state.models import EligibilityCase

console = Console()


WELCOME = f"""
# NC FNS Eligibility Screening Agent (POC)

Informal likelihood screen for **North Carolina Food and Nutrition Services** (SNAP).

- Ruleset: `{RULESET.id}` ({RULESET.effective_from} → {RULESET.effective_to})
- I use curated public documents + deterministic income math
- I **cannot** submit applications or contact DSS
- Please **do not** share SSN or full street address
- Sessions are stored in **Redis** (start the Compose stack so Redis is available)

Commands: `/quit` `/reset` `/state` `/debug on|off`
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NC FNS eligibility screening agent")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show extraction/plan debug after each turn",
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

    console.print(Markdown(WELCOME))
    console.print(
        f"[dim]Session {sid} · model: {settings.openai_model} · "
        f"redis: {settings.public_redis_url}[/dim]\n"
    )

    if args.script:
        _run_script(args.script, case, store, sid, debug)
        return

    while True:
        try:
            user = console.input("[bold cyan]You>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye.")
            break

        if not user:
            continue
        if user.lower() in {"/quit", "/exit", "quit", "exit"}:
            console.print("Goodbye.")
            break
        if user.lower() == "/reset":
            case = store.reset(sid)
            console.print("[green]Session reset.[/green]")
            continue
        if user.lower() == "/state":
            console.print_json(json.dumps(case.known_summary(), default=str))
            continue
        if user.lower() == "/debug on":
            debug = True
            console.print("Debug on.")
            continue
        if user.lower() == "/debug off":
            debug = False
            console.print("Debug off.")
            continue

        result = process_turn(user, case)
        case = result.case
        store.set(sid, case)

        console.print()
        console.print(Panel(Markdown(result.reply), title="Agent", border_style="green"))
        if debug:
            console.print(
                Panel(
                    json.dumps(result.debug, indent=2, default=str),
                    title="Debug",
                    border_style="dim",
                )
            )


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
        console.print(Panel(Markdown(result.reply), title="Agent", border_style="green"))
        if debug:
            console.print(
                Panel(
                    json.dumps(result.debug, indent=2, default=str),
                    title="Debug",
                    border_style="dim",
                )
            )


if __name__ == "__main__":
    main()

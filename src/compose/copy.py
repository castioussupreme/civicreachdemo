"""Code-owned user-facing copy (scope intro + apply next steps)."""

from __future__ import annotations

from src.programs.models import ProgramMeta
from src.programs.registry import get_program


def resolve_program(slug: str) -> ProgramMeta | None:
    try:
        return get_program(slug)
    except Exception:
        return None


def scope_intro_blurb(program: ProgramMeta) -> str:
    """
    Super-short covers / doesn't — set expectations once early in the chat.
    """
    name = program.display_name or "this program"
    area = program.service_area_name or "the program service area"
    return (
        f"**What this screen covers:** a quick public gross-income check for {name} "
        f"({area}) using household size and before-tax income.\n"
        f"**What it doesn't:** file an application, check assets/resources, student "
        f"exemptions in full, or replace a decision by the agency."
    )


def continue_cta() -> str:
    """Invite the user to start screening after the scope intro."""
    return (
        "If that sounds useful, say **yes** (or share a bit about your household and income) "
        "and we can start the quick check."
    )


def build_opening_message(program: ProgramMeta) -> str:
    """
    First assistant message: greeting + covers/doesn't + go-ahead CTA.

    Pack ``opening_message`` is a short greeting only; scope is code-owned so it
    always appears before any household/income questions.
    """
    greeting = (program.opening_message or "").strip()
    if "What this screen covers" in greeting:
        # Pack already embeds scope (e.g. tests override a full message)
        return greeting
    if not greeting:
        name = program.display_name or "this program"
        greeting = f"Hi — I can help with a quick check on whether you might qualify for {name}."
    return f"{greeting}\n\n{scope_intro_blurb(program)}\n\n{continue_cta()}"


def next_steps_blurb(program: ProgramMeta) -> str:
    """Official next steps after a terminal screen (agent never applies for them)."""
    channel = program.apply_channel or "your local agency"
    if program.apply_url and program.apply_label:
        return (
            f"**Next steps (official):** apply via {program.apply_label} "
            f"({program.apply_url}) or {channel}. "
            f"I can't submit or log in for you — only you (or someone you authorize) can."
        )
    if program.apply_url:
        return (
            f"**Next steps (official):** apply at {program.apply_url} or contact {channel}. "
            f"I can't submit an application for you."
        )
    return (
        f"**Next steps (official):** contact {channel} for a real determination. "
        f"I can't submit an application for you."
    )

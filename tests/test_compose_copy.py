"""Scope intro + next-steps copy (no LLM)."""

from __future__ import annotations

from unittest.mock import patch

from src.compose.copy import build_opening_message, next_steps_blurb, scope_intro_blurb
from src.compose.response import compose_response, is_terminal_assessment
from src.planner.missing import PlanResult
from src.programs.registry import get_program
from src.state.models import Assessment, AssessmentStatus, Stage, fresh_case


def test_scope_intro_covers_and_does_not() -> None:
    prog = get_program("nc-fns")
    text = scope_intro_blurb(prog)
    assert "covers" in text.lower()
    assert "doesn't" in text.lower() or "does not" in text.lower()
    assert "application" in text.lower()
    assert "North Carolina" in text or "FNS" in text or "SNAP" in text


def test_build_opening_has_scope_before_intake() -> None:
    prog = get_program("nc-fns")
    text = build_opening_message(prog)
    assert text.index("What this screen covers") < text.lower().index("yes")
    assert "Can you start by telling me" not in text
    assert "FNS" in text or "SNAP" in text or "food assistance" in text


def test_next_steps_nc_epass() -> None:
    prog = get_program("nc-fns")
    text = next_steps_blurb(prog)
    assert "epass.nc.gov" in text
    assert "can't submit" in text.lower() or "cannot submit" in text.lower()


def test_next_steps_calfresh_benefitscal() -> None:
    prog = get_program("ca-calfresh")
    text = next_steps_blurb(prog)
    assert "benefitscal.com" in text


def test_scope_and_next_steps_flags() -> None:
    case = fresh_case(program_slug="nc-fns")
    blurb = scope_intro_blurb(get_program("nc-fns"))
    text = blurb + "\n\nAbout how many people?"
    case.scope_intro_given = True
    assert text.startswith("**What this screen covers:**")

    assessment = Assessment(
        status=AssessmentStatus.LIKELY_ELIGIBLE,
        reasons=["under threshold"],
        rule_version="nc-fns-screening-2025-10",
        source_ids=["nc-fns-income-limits"],
        threshold_used=3526.0,
        normalized_gross_monthly=3000.0,
        household_size=2,
    )
    assert is_terminal_assessment(assessment)
    next_text = "You may qualify.\n\n" + next_steps_blurb(get_program("nc-fns"))
    case.next_steps_given = True
    assert "epass.nc.gov" in next_text


def test_post_assess_flag_skips_reinterview_path() -> None:
    """compose_response with post_assess=True should not re-append next steps."""
    case = fresh_case(program_slug="nc-fns")
    case.scope_intro_given = True
    case.next_steps_given = True
    case.disclaimer_given = True
    case.stage = Stage.ASSESSED
    assessment = Assessment(
        status=AssessmentStatus.LIKELY_ELIGIBLE,
        reasons=["ok"],
        rule_version="x",
        source_ids=[],
        threshold_used=2610.0,
        normalized_gross_monthly=2000.0,
        household_size=1,
    )
    case.assessment = assessment
    plan = PlanResult(
        missing_fields=[],
        stage=Stage.ASSESSED,
        next_question_hint="",
        ready_to_assess=True,
        open_contradictions=[],
    )
    with patch("src.compose.response.chat_text", return_value="Happy to clarify the prior screen."):
        text = compose_response(
            case=case,
            plan=plan,
            assessment=assessment,
            citations=[],
            user_message="thanks",
            post_assess=True,
        )
    assert "Happy to clarify" in text
    assert text.count("epass.nc.gov") == 0

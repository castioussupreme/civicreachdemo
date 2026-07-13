"""Terminal compose: structured grounding, repair, template fallback (LLM mocked)."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.compose.response import compose_response
from src.eligibility.ruleset import load_ruleset
from src.planner.missing import PlanResult
from src.retrieval.kb import Citation
from src.state.models import (
    Assessment,
    AssessmentStatus,
    CaseField,
    EligibilityCase,
    FieldStatus,
    Stage,
)


def _case() -> EligibilityCase:
    rs = load_ruleset("nc-fns")
    case = EligibilityCase(
        program_slug="nc-fns",
        ruleset_id=rs.id,
        as_of="2026-03-01",
        ruleset_effective_from=rs.effective_from,
        ruleset_effective_to=rs.effective_to,
    )
    case.lives_in_service_area = CaseField(status=FieldStatus.KNOWN, value=True)
    case.household_size = CaseField(status=FieldStatus.KNOWN, value=2)
    case.stage = Stage.ASSESSED
    return case


def _assessment() -> Assessment:
    return Assessment(
        status=AssessmentStatus.LIKELY_ELIGIBLE,
        reasons=["Income under threshold."],
        rule_version="nc-fns-screening-2025-10",
        source_ids=["nc-fns-income-limits"],
        threshold_used=3526.0,
        normalized_gross_monthly=3000.0,
        household_size=2,
        caveats=["This is an informal screening only."],
    )


def _plan() -> PlanResult:
    return PlanResult(
        missing_fields=[],
        stage=Stage.ASSESSED,
        next_question_hint="",
        ready_to_assess=True,
        open_contradictions=[],
    )


def _cite() -> Citation:
    return Citation(
        source_id="nc-fns-income-limits",
        title="NC SNAP/FNS gross monthly income limits (FY 2026)",
        url="https://morefood.org/using-snap/am-i-eligible/",
        snippet="table",
    )


def test_terminal_compose_accepts_valid_grounding() -> None:
    payload = {
        "message": (
            "With about $3,000 a month for 2 people, you're under the $3,526 public limit — "
            "you may qualify on this informal screen."
        ),
        "grounding": {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 3526,
            "household_size": 2,
        },
    }
    with patch("src.compose.response.chat_json", return_value=payload) as mock_json:
        text = compose_response(
            case=_case(),
            plan=_plan(),
            assessment=_assessment(),
            citations=[_cite()],
            user_message="3000 monthly",
        )
    assert mock_json.call_count == 1
    assert "$3,000" in text or "3000" in text
    assert "may qualify" in text.lower()
    # Should not fall through to template phrasing only
    assert "Based on what you shared" not in text or "With about" in text


def test_terminal_compose_repairs_then_accepts() -> None:
    bad = {
        "message": "You may qualify under the $2,610 limit.",
        "grounding": {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 2610,  # wrong
            "household_size": 2,
        },
    }
    good = {
        "message": (
            "For 2 people at about $3,000 monthly vs the $3,526 public limit, "
            "you may qualify on this informal screen."
        ),
        "grounding": {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 3526,
            "household_size": 2,
        },
    }
    with patch("src.compose.response.chat_json", side_effect=[bad, good]) as mock_json:
        text = compose_response(
            case=_case(),
            plan=_plan(),
            assessment=_assessment(),
            citations=[_cite()],
            user_message="3000 monthly",
        )
    assert mock_json.call_count == 2
    assert "3,526" in text or "3526" in text
    assert "2,610" not in text and "2610" not in text


def test_terminal_compose_template_fallback_when_repair_fails() -> None:
    bad = {
        "message": "Looks good!",
        "grounding": {"status": "likely_ineligible"},  # wrong status + missing numbers
    }
    still_bad = {
        "message": "Still wrong",
        "grounding": {
            "status": "likely_eligible",
            "monthly_income": 9999,
            "threshold": 3526,
            "household_size": 2,
        },
    }
    with patch("src.compose.response.chat_json", side_effect=[bad, still_bad]) as mock_json:
        text = compose_response(
            case=_case(),
            plan=_plan(),
            assessment=_assessment(),
            citations=[_cite()],
            user_message="3000 monthly",
        )
    assert mock_json.call_count == 2
    # Template from assessment
    assert "$3,000" in text
    assert "$3,526" in text
    assert "may qualify" in text.lower()
    assert "morefood.org" in text or "Public" in text or "More:" in text


def test_terminal_compose_template_on_empty_message() -> None:
    empty = {"message": "", "grounding": {"status": "likely_eligible"}}
    still_empty = {"message": "  ", "grounding": {}}
    with patch("src.compose.response.chat_json", side_effect=[empty, still_empty]):
        text = compose_response(
            case=_case(),
            plan=_plan(),
            assessment=_assessment(),
            citations=[],
            user_message="done",
        )
    assert "$3,000" in text
    assert "$3,526" in text


def test_intake_still_uses_chat_text() -> None:
    case = _case()
    case.stage = Stage.COLLECTING
    plan = PlanResult(
        missing_fields=["income_amount"],
        stage=Stage.COLLECTING,
        next_question_hint="About how much income?",
        ready_to_assess=False,
        open_contradictions=[],
    )
    with (
        patch("src.compose.response.chat_text", return_value="About how much do you make?") as ct,
        patch("src.compose.response.chat_json") as cj,
    ):
        text = compose_response(
            case=case,
            plan=plan,
            assessment=None,
            citations=[],
            user_message="we are 2 people",
        )
    ct.assert_called_once()
    cj.assert_not_called()
    assert "how much" in text.lower()


def test_disclaimer_flag_set_on_terminal() -> None:
    case = _case()
    assert case.disclaimer_given is False
    payload = {
        "message": (
            "At $3,000 vs $3,526 for 2 people you may qualify. "
            "This is informal — county DSS decides."
        ),
        "grounding": {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 3526,
            "household_size": 2,
        },
    }
    with patch("src.compose.response.chat_json", return_value=payload):
        compose_response(
            case=case,
            plan=_plan(),
            assessment=_assessment(),
            citations=[],
        )
    assert case.disclaimer_given is True

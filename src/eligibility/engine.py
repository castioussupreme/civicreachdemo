from __future__ import annotations

from src.eligibility.ruleset import RULESET, Ruleset
from src.programs.registry import get_program, get_ruleset_by_id
from src.state.models import (
    Assessment,
    AssessmentStatus,
    EligibilityCase,
    FieldStatus,
)


def _service_area(case: EligibilityCase) -> tuple[str, str]:
    """Return (full name, short code) for residency messaging."""
    try:
        prog = get_program(case.program_slug or "nc-fns")
        return prog.service_area_name, prog.display_name
    except Exception:
        return "the program service area", "this program"


def _ruleset_for_case(case: EligibilityCase, ruleset: Ruleset | None) -> Ruleset:
    if ruleset is not None:
        return ruleset
    if case.program_slug and case.ruleset_id:
        try:
            return get_ruleset_by_id(case.program_slug, case.ruleset_id)
        except Exception:
            pass
    return RULESET


def calculate_eligibility(
    case: EligibilityCase,
    ruleset: Ruleset | None = None,
) -> Assessment:
    """
    Deterministic screening assessment.
    Pure function of case state + versioned ruleset (pinned on the case when set).
    """
    ruleset = _ruleset_for_case(case, ruleset)
    source_ids = [ruleset.source_id, *ruleset.supporting_source_ids]
    caveats: list[str] = [
        "This is an informal screening only—not an official DSS determination.",
        (
            f"Ruleset {ruleset.id} effective from {ruleset.effective_from}"
            + (f" to {ruleset.effective_to}" if ruleset.effective_to else " (open-ended)")
            + "."
        ),
    ]
    # NC FNS-style 130% note only when that supporting doc is declared on the pack
    if "nc-fns-gross-income-tests" in ruleset.supporting_source_ids:
        caveats.append(
            "Some households may face a stricter (~130%) gross income test; only DSS "
            "decides which test applies (this screen uses the public 200% table only)."
        )
    reasons: list[str] = []

    area, program_name = _service_area(case)

    # Residency hard gate for the program's service area
    if case.lives_in_nc.status == FieldStatus.KNOWN and case.lives_in_nc.value is False:
        overview = (
            "nc-fns-overview"
            if case.program_slug == "nc-fns"
            else (
                ruleset.supporting_source_ids[0]
                if ruleset.supporting_source_ids
                else ruleset.source_id
            )
        )
        return Assessment(
            status=AssessmentStatus.LIKELY_INELIGIBLE,
            reasons=[
                f"User indicated they do not live in {area}; "
                f"{program_name} is for {area} residents."
            ],
            rule_version=ruleset.id,
            source_ids=[*source_ids, overview],
            caveats=[*caveats, "Other jurisdictions administer their own assistance programs."],
        )

    if not case.lives_in_nc.is_usable():
        return Assessment(
            status=AssessmentStatus.NEEDS_MORE_INFORMATION,
            reasons=[f"{area} residency has not been confirmed."],
            rule_version=ruleset.id,
            source_ids=source_ids,
            caveats=caveats,
        )

    if not case.household_size.is_usable():
        return Assessment(
            status=AssessmentStatus.NEEDS_MORE_INFORMATION,
            reasons=["Household size is missing or not confirmed."],
            rule_version=ruleset.id,
            source_ids=source_ids,
            caveats=caveats,
        )

    # Income readiness
    income_status = case.normalized_gross_monthly.status
    if income_status == FieldStatus.UNKNOWN or case.normalized_gross_monthly.value is None:
        if case.income_amount.status == FieldStatus.UNCERTAIN:
            return Assessment(
                status=AssessmentStatus.NEEDS_MORE_INFORMATION,
                reasons=[
                    "Income was stated approximately; need a clearer amount "
                    "and whether it is daily/weekly/monthly and gross household income."
                ],
                rule_version=ruleset.id,
                source_ids=[*source_ids, "nc-fns-income-limits"],
                caveats=caveats,
            )
        return Assessment(
            status=AssessmentStatus.NEEDS_MORE_INFORMATION,
            reasons=["Gross household monthly income is not yet established."],
            rule_version=ruleset.id,
            source_ids=[*source_ids, "nc-fns-income-limits"],
            caveats=caveats,
        )

    size_val = case.household_size.value
    monthly_val = case.normalized_gross_monthly.value
    if size_val is None or monthly_val is None:
        return Assessment(
            status=AssessmentStatus.NEEDS_MORE_INFORMATION,
            reasons=["Household size or income value missing after validation."],
            rule_version=ruleset.id,
            source_ids=source_ids,
            caveats=caveats,
        )
    size = int(size_val)
    monthly = float(monthly_val)
    threshold = ruleset.threshold_for_household(size)

    # Uncertain normalized income (net take-home and/or individual-only in multi-person HH)
    if income_status == FieldStatus.UNCERTAIN:
        return _assess_uncertain_income(
            case=case,
            monthly=monthly,
            size=size,
            threshold=threshold,
            ruleset=ruleset,
            source_ids=source_ids,
            caveats=caveats,
        )

    # Gross income comparison (confirmed gross household)
    under = monthly <= threshold
    if under:
        reasons.append(
            f"Normalized gross monthly income ${monthly:,.2f} is at or below "
            f"the public screening threshold ${threshold:,.2f} for a household of {size}."
        )
        status = AssessmentStatus.LIKELY_ELIGIBLE
    else:
        reasons.append(
            f"Normalized gross monthly income ${monthly:,.2f} is above "
            f"the public screening threshold ${threshold:,.2f} for a household of {size}."
        )
        status = AssessmentStatus.LIKELY_INELIGIBLE

    # Student: income screen only — full exemptions live in knowledge/nc-fns-student-rules.md
    # (not modeled in code). Keep that policy doc aligned if this behavior changes. See AGENTS.md.
    if case.is_student.is_usable() and case.is_student.value is True:
        source_ids = [*source_ids, "nc-fns-student-rules"]
        caveats.append(
            "College student rules are not fully modeled here. Students often need an "
            "additional exemption beyond the income screen; DSS or campus outreach must decide."
        )
        if status == AssessmentStatus.LIKELY_ELIGIBLE:
            status = AssessmentStatus.UNABLE_TO_DETERMINE
            reasons.append(
                "On the simple gross-income table alone this would look like a pass, "
                "but student-specific FNS rules are not evaluated by this tool — "
                "so overall we cannot give a confident screening result."
            )
        else:
            reasons.append(
                "Student status does not change a failed gross-income screen on this tool."
            )

    if case.elderly_or_disabled_member.is_usable() and case.elderly_or_disabled_member.value:
        caveats.append(
            "Household may include elderly or disabled members; DSS may apply "
            "different resource or income treatment not modeled here."
        )

    return Assessment(
        status=status,
        reasons=reasons,
        rule_version=ruleset.id,
        source_ids=list(dict.fromkeys(source_ids)),
        threshold_used=threshold,
        normalized_gross_monthly=monthly,
        household_size=size,
        caveats=caveats,
    )


def _assess_uncertain_income(
    *,
    case: EligibilityCase,
    monthly: float,
    size: int,
    threshold: float,
    ruleset: Ruleset,
    source_ids: list[str],
    caveats: list[str],
) -> Assessment:
    is_net = case.gross_or_net.is_usable() and case.gross_or_net.value == "net"
    is_individual = (
        case.household_or_individual.is_usable()
        and case.household_or_individual.value == "individual"
        and size > 1
    )

    # Safe lower-bound math (no tax brackets, no inventing other members' pay):
    # true gross household income ≥ stated take-home, and ≥ stated individual income.
    if monthly > threshold and (is_net or is_individual):
        if is_net and is_individual:
            bound_why = (
                f"You shared take-home income for one person of about ${monthly:,.2f}/month. "
                f"Full household before-tax income is at least that high."
            )
        elif is_net:
            bound_why = (
                f"You shared take-home (after-tax) income of about ${monthly:,.2f}/month. "
                f"Before-tax income is at least that high."
            )
        else:
            bound_why = (
                f"You shared one person's income of about ${monthly:,.2f}/month. "
                f"Total household income is at least that high."
            )
        return Assessment(
            status=AssessmentStatus.LIKELY_INELIGIBLE,
            reasons=[
                f"{bound_why} The public gross limit for a household of {size} is "
                f"${threshold:,.2f} — so this simple screen points to likely not eligible."
            ],
            rule_version=ruleset.id,
            source_ids=[*source_ids, "nc-fns-income-limits"],
            threshold_used=threshold,
            normalized_gross_monthly=monthly,
            household_size=size,
            caveats=[
                *caveats,
                "Bound uses a lower bound on income (take-home and/or one person only); "
                "no tax reverse-calculation or invented household totals.",
            ],
        )

    extra: list[str] = []
    if is_net:
        extra.append(
            "Income was given as take-home (after taxes). This screen compares "
            "before-tax (gross) income to the public table. We do not reverse-calculate "
            "gross from tax brackets — that would be guesswork."
        )
        source_ids = [*source_ids, "nc-fns-income-limits"]
    if is_individual:
        extra.append(
            "Income may be for one person only; screening needs total household income "
            "for everyone who buys and prepares food together. We do not invent "
            "other members' earnings."
        )
        source_ids = [*source_ids, "nc-fns-income-limits"]

    parts: list[str] = []
    if is_net:
        parts.append("take-home")
    if is_individual:
        parts.append("one-person")
    label = " / ".join(parts) if parts else "provisional"

    return Assessment(
        status=AssessmentStatus.UNABLE_TO_DETERMINE,
        reasons=extra or ["Income details are too uncertain to complete a reliable gross screen."],
        rule_version=ruleset.id,
        source_ids=list(dict.fromkeys([*source_ids, "nc-fns-income-limits"])),
        threshold_used=threshold,
        normalized_gross_monthly=monthly,
        household_size=size,
        caveats=[
            *caveats,
            f"Your {label} amount normalized to about ${monthly:,.2f}/month "
            f"(not confirmed full gross household income). Public gross threshold for "
            f"household of {size}: ${threshold:,.2f}. "
            f"If you know approximate before-tax total household income, we can re-run "
            f"this simple screen; otherwise DSS can review a full application.",
        ],
    )

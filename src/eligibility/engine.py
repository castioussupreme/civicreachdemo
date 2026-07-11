from __future__ import annotations

from src.eligibility.ruleset import RULESET, Ruleset
from src.state.models import (
    Assessment,
    AssessmentStatus,
    EligibilityCase,
    FieldStatus,
)


def calculate_eligibility(
    case: EligibilityCase,
    ruleset: Ruleset = RULESET,
) -> Assessment:
    """
    Deterministic screening assessment.
    Pure function of case state + versioned ruleset.
    """
    source_ids = [ruleset.source_id, "agent-disclaimer", "nc-fns-general-requirements"]
    caveats: list[str] = [
        "This is an informal screening only—not an official DSS determination.",
        (f"Ruleset {ruleset.id} effective {ruleset.effective_from} to {ruleset.effective_to}."),
        "Some households may face a different (e.g. 130%) gross income test; DSS decides.",
    ]
    reasons: list[str] = []

    # Residency hard gate for NC FNS screening
    if case.lives_in_nc.status == FieldStatus.KNOWN and case.lives_in_nc.value is False:
        return Assessment(
            status=AssessmentStatus.LIKELY_INELIGIBLE,
            reasons=[
                "User indicated they do not live in North Carolina; "
                "NC FNS is for North Carolina residents."
            ],
            rule_version=ruleset.id,
            source_ids=[*source_ids, "nc-fns-overview"],
            caveats=[*caveats, "Other states administer their own SNAP programs."],
        )

    if not case.lives_in_nc.is_usable():
        return Assessment(
            status=AssessmentStatus.NEEDS_MORE_INFORMATION,
            reasons=["North Carolina residency has not been confirmed."],
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
        # Check if we have partial income
        if case.income_amount.status == FieldStatus.UNCERTAIN:
            return Assessment(
                status=AssessmentStatus.NEEDS_MORE_INFORMATION,
                reasons=[
                    "Income was stated approximately; need a clearer amount "
                    "and whether it is monthly/weekly and gross household income."
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

    # Net income or individual-only income → cannot firmly conclude from gross screen
    if income_status == FieldStatus.UNCERTAIN:
        extra = []
        if case.gross_or_net.is_usable() and case.gross_or_net.value == "net":
            extra.append("Income appears to be net (after taxes); this screen uses gross income.")
            source_ids = [*source_ids, "nc-fns-income-limits"]
        if (
            case.household_or_individual.is_usable()
            and case.household_or_individual.value == "individual"
            and size > 1
        ):
            extra.append(
                "Income may be individual only; screening needs total household income "
                "for everyone who buys and prepares food together."
            )
        return Assessment(
            status=AssessmentStatus.UNABLE_TO_DETERMINE,
            reasons=extra
            or ["Income details are too uncertain to complete a reliable gross screen."],
            rule_version=ruleset.id,
            source_ids=[*source_ids, "nc-fns-income-limits"],
            threshold_used=threshold,
            normalized_gross_monthly=monthly,
            household_size=size,
            caveats=[
                *caveats,
                f"Provisional normalized monthly figure used for discussion: ${monthly:,.2f}; "
                f"public table threshold for household of {size}: ${threshold:,.2f}.",
            ],
        )

    # Gross income comparison
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

    # Student caveat: never claim full student determination
    if case.is_student.is_usable() and case.is_student.value is True:
        source_ids = [*source_ids, "nc-fns-student-rules"]
        caveats.append(
            "User indicated college student status. Students often need an additional "
            "exemption beyond income; DSS (or campus outreach) must evaluate student rules."
        )
        if status == AssessmentStatus.LIKELY_ELIGIBLE:
            # Soften: still pass gross screen but flag uncertainty
            status = AssessmentStatus.UNABLE_TO_DETERMINE
            reasons.append(
                "Gross income screen may pass, but student-specific rules are not "
                "fully evaluated by this POC—treat as uncertain overall."
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

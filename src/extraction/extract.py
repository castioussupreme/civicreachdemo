from __future__ import annotations

import json

from src.extraction.schema import ExtractionResult, coerce_extraction
from src.llm.client import chat_json
from src.programs.registry import get_program
from src.state.models import EligibilityCase


def _extraction_system(*, service_area: str, program_name: str) -> str:
    return f"""You extract structured facts for a {program_name} eligibility screening case.
Return ONLY a JSON object. Do not invent facts the user did not imply.
If the user is approximate ("about 2500"), still extract the number but set lower confidence.
If the user answers multiple questions at once, extract all facts you can.

Service area for residency: {service_area}.
Set lives_in_nc true only if the user lives in {service_area}; false if they live elsewhere.
(The field name lives_in_nc is historical; it means "lives in the program service area.")

Schema:
{{
  "facts": {{
    "lives_in_nc": true|false|null,
    "household_size": number|null,
    "income_amount": number|null,
    "income_period": "daily"|"weekly"|"biweekly"|"semimonthly"|"monthly"|"annual"|null,
    "gross_or_net": "gross"|"net"|null,
    "household_or_individual": "household"|"individual"|null,
    "is_student": true|false|null,
    "elderly_or_disabled_member": true|false|null,
    "confirm_field": string|null,
    "confirm_value": string|number|boolean|null,
    "confidence": {{ "<field>": 0.0-1.0 }}
  }},
  "user_intents": ["eligibility_screening"|"policy_question"|"greeting"|"other"],
  "policy_question": string|null,
  "notes": string|null
}}

Rules:
- income_amount should be numeric only (no $).
- "2k a month" -> income_amount 2000, income_period monthly.
- "200 a day" / "200/day" / "I make 200 daily" -> income_amount 200, income_period daily.
- "per day" or "a day" means daily (not weekly).
- "every two weeks" / biweekly -> biweekly. "twice a month" / "1st and 15th" / semi-monthly -> semimonthly (NOT biweekly).
- "I make about $2,500" without period -> income_amount 2500, income_period null, confidence lower.
- Hourly wages ("$15 an hour"): set income_amount to the hourly rate, income_period null,
  notes="hourly wage — need hours per week"; do NOT invent hours or monthly total.
- If previous_question asks for before-tax / gross amount and the user gives a number,
  set income_amount to that number and gross_or_net to "gross" (keep income_period if unchanged).
- If previous_question asks for total household income and the user gives a number,
  set income_amount to that number and household_or_individual to "household".
- If they say they only know take-home / don't know before-tax, set gross_or_net to "net"
  and leave income_amount as previously known take-home (do not invent a gross amount).
- If they only know their own income (not others), household_or_individual=individual.
- Never invent gross from net using tax rates or brackets.
- Never invent other household members' income.
- Do not extract SSN or addresses.
- confirm_field/confirm_value only if user is resolving a prior contradiction.
- Use recent_conversation only to interpret short answers (e.g. "yes", "monthly", "the second one").
- Prefer facts clearly stated or implied in the latest message; do not re-extract old turns as new facts.
"""


def extract_facts(
    message: str,
    case: EligibilityCase,
    *,
    previous_question: str | None = None,
) -> ExtractionResult:
    try:
        prog = get_program(case.program_slug or "nc-fns")
        service_area = prog.service_area_name
        program_name = prog.display_name
    except Exception:
        service_area = "the program service area"
        program_name = "public benefits"
    system = _extraction_system(service_area=service_area, program_name=program_name)

    # Last few turns for anaphora only ("yes", "the higher one") — case slots remain truth.
    recent = [
        {"role": t.role, "text": t.text[:400]}
        for t in case.recent_turns[-4:]
        if t.role == "user" or t.role == "assistant"
    ]
    user_payload = {
        "message": message,
        "previous_question": previous_question or case.last_question,
        "service_area": service_area,
        "current_state": case.known_summary(),
        "recent_conversation": recent,
        "open_contradictions": [
            {
                "field": c.field,
                "previous_value": c.previous_value,
                "proposed_value": c.proposed_value,
                "turn": c.turn,
                "resolved": c.resolved,
            }
            for c in case.contradictions
            if not c.resolved
        ],
    }

    data = chat_json(
        system=system,
        user=json.dumps(user_payload),
        temperature=0.0,
    )
    return coerce_extraction(data)

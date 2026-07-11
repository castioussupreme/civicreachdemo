from __future__ import annotations

import json

from src.extraction.schema import ExtractionResult, coerce_extraction
from src.llm.client import chat_json
from src.state.models import EligibilityCase

EXTRACTION_SYSTEM = """You extract structured facts for an NC FNS (SNAP) eligibility screening case.
Return ONLY a JSON object. Do not invent facts the user did not imply.
If the user is approximate ("about 2500"), still extract the number but set lower confidence.
If the user answers multiple questions at once, extract all facts you can.

Schema:
{
  "facts": {
    "lives_in_nc": true|false|null,
    "household_size": number|null,
    "income_amount": number|null,
    "income_period": "weekly"|"biweekly"|"monthly"|"annual"|null,
    "gross_or_net": "gross"|"net"|null,
    "household_or_individual": "household"|"individual"|null,
    "is_student": true|false|null,
    "elderly_or_disabled_member": true|false|null,
    "confirm_field": string|null,
    "confirm_value": string|number|boolean|null,
    "confidence": { "<field>": 0.0-1.0 }
  },
  "user_intents": ["eligibility_screening"|"policy_question"|"greeting"|"other"],
  "policy_question": string|null,
  "notes": string|null
}

Rules:
- income_amount should be numeric only (no $).
- "2k a month" -> income_amount 2000, income_period monthly.
- "I make about $2,500" without period -> income_amount 2500, income_period null, confidence lower.
- Do not extract SSN or addresses.
- confirm_field/confirm_value only if user is resolving a prior contradiction.
"""


def extract_facts(
    message: str,
    case: EligibilityCase,
    *,
    previous_question: str | None = None,
) -> ExtractionResult:
    user_payload = {
        "message": message,
        "previous_question": previous_question or case.last_question,
        "current_state": case.known_summary(),
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
        system=EXTRACTION_SYSTEM,
        user=json.dumps(user_payload),
        temperature=0.0,
    )
    return coerce_extraction(data)

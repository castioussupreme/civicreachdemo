# General NC FNS requirements (screening summary)

**Source id:** `nc-fns-general-requirements`
**Public source:** More In My Basket - Am I Eligible?
**URL:** https://morefood.org/using-snap/am-i-eligible/

## General requirements (public summary)

Applicants generally must:

1. Be U.S. citizens, legal permanent residents, or have another eligible immigration status (international students are not eligible under current guidelines cited by outreach materials).
2. Meet residency requirements (for North Carolina FNS, that includes living in North Carolina).
3. Have monthly income at or below applicable SNAP/FNS program limits for their household size.

## What “household” means (simplified)

For screening purposes, household size is the number of people who **buy and prepare food together**. Official household composition rules are more detailed and are determined by DSS.

> The CLI/planner asks the same “buy and prepare food together” wording via
> `src/planner/missing.py` (`QUESTION_HINTS`) — keep that phrase aligned (`AGENTS.md`).

## What this POC screens

This agent focuses on:

- North Carolina residency (self-reported)
- Household size
- Gross household income normalized to a monthly amount
- Optional student flag (triggers caution, not a full student determination)

It does **not** fully evaluate immigration status, resources/assets, deductions/net income, ABAWD time limits, or other specialized rules.

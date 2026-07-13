# NC SNAP/FNS gross monthly income limits

**Source id:** `nc-fns-income-limits`
**Public source:** More In My Basket - Am I Eligible?
**URL:** https://morefood.org/using-snap/am-i-eligible/
**Effective:** October 1, 2025 - September 30, 2026
**Ruleset id used by this POC:** `nc-fns-screening-2025-10`

> **Dual copy:** The same gross monthly table is hard-coded for eligibility math in
> `src/eligibility/ruleset.py` (`RULESET`). When changing numbers, dates, or the ruleset id,
> update that file and this doc together (see `AGENTS.md`). Public provenance is the URL above.

## Important caveats

- The public table below is labeled **Maximum Gross Monthly Income (200%)**.
- **Some individuals must meet standard gross income limits (130%)**, and **DSS will make this determination**.
- Meeting the gross income screen means a household **may** be eligible—not that they are approved.
- Official eligibility also considers household composition, resources, citizenship/immigration status, and other rules this POC does not fully evaluate.

## Gross monthly income table (public screening table)

|         Household size | Maximum gross monthly income |
| ---------------------: | ---------------------------: |
|                      1 |                       $2,610 |
|                      2 |                       $3,526 |
|                      3 |                       $4,442 |
|                      4 |                       $5,360 |
|                      5 |                       $6,276 |
|                      6 |                       $7,194 |
|                      7 |                       $8,112 |
|                      8 |                       $9,030 |
| Each additional member |                        +$918 |

## Maximum benefit amounts (context only; not used for eligibility math in this POC)

Public materials also list maximum monthly allotments by household size for the same effective period. Allotments may be lower than the maximum. This POC does **not** compute benefit amounts.

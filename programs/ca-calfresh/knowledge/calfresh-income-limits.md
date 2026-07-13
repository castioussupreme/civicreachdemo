# CalFresh gross monthly income limits (FFY 2026)

**Source id:** `calfresh-income-limits`
**Public source:** County/CDSS CalFresh gross income charts (200% FPL for BBCE/MCE)
**URL:** https://dpss.lacounty.gov/en/food/calfresh/gross-income.html
**Effective:** October 1, 2025 – September 30, 2026
**Ruleset id used by this POC:** `ca-calfresh-screening-2025-10`

> **Dual copy:** Same table as `programs/ca-calfresh/rules/2025-10.yaml`. See `AGENTS.md`.

## Important caveats

- Table is the public **200% of federal poverty** gross monthly standard used for many CalFresh households under broad-based categorical eligibility.
- Some households face a **130%** gross test or other rules; **county eligibility workers decide**.
- Meeting this informal screen means a household **may** be eligible—not that they are approved.
- Households with elderly or disabled members may have different treatment (not fully modeled here).

## Gross monthly income table (public screening table)

| Household size | Maximum gross monthly income (200% FPL) |
|---------------:|----------------------------------------:|
| 1 | $2,610 |
| 2 | $3,526 |
| 3 | $4,442 |
| 4 | $5,360 |
| 5 | $6,276 |
| 6 | $7,192 |
| 7 | $8,110 |
| 8 | $9,026 |
| Each additional member | +$918 |

Unique marker: **CALFRESH_LIMITS_TABLE**.

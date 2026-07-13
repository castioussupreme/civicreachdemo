# Agent instructions (this repo)

POC NC FNS informal screening agent. Prefer small, correct changes over new infrastructure.

## Architecture (do not regress)

- **Single runtime:** only the agent API runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). CLI and smoke are HTTP clients via `AgentApiClient` / `PUBLIC_BASE_URL`.
- **Hybrid control:** LLM extracts language and composes replies; **code** owns safety, case state, planner, and eligibility math.
- **RAG is citations only:** retrieval must not invent dollar thresholds. Thresholds come from `RULESET` in code.

## Dual copy of income thresholds (intentional)

Eligibility **math** lives in Python; the **public table** also lives in curated markdown for RAG and human reading.

| Role                                | Path                                                                |
| ----------------------------------- | ------------------------------------------------------------------- |
| Code (authoritative for assessment) | `src/eligibility/ruleset.py` → `RULESET`                            |
| Knowledge (RAG / display table)     | `knowledge/nc-fns-income-limits.md`                                 |
| Manifest metadata                   | `knowledge/manifest.json` entry `nc-fns-income-limits`              |
| Soft CI guard                       | `tests/test_knowledge.py` (`test_income_doc_matches_ruleset_table`) |

**Public provenance (both copies must stay aligned with this source):**

- Publisher: More In My Basket - Am I Eligible?
- URL: https://morefood.org/using-snap/am-i-eligible/
- Table label: Maximum Gross Monthly Income (**200%**), FY window **2025-10-01 - 2026-09-30**
- Ruleset id: `nc-fns-screening-2025-10`
- Knowledge source id: `nc-fns-income-limits`

### When you change thresholds, dates, or ruleset id

Update **all** of these in the same change:

1. `src/eligibility/ruleset.py` (`RULESET`: table, `additional_member_increment`, `effective_from` / `effective_to`, `id`, `source_id`, description)
2. `knowledge/nc-fns-income-limits.md` (table, effective dates, ruleset id line)
3. `knowledge/manifest.json` (`nc-fns-income-limits` `effective_from` / `effective_to` / notes if needed)
4. Smoke/fixtures that hardcode thresholds (e.g. `src/smoke.py` `EXPECTED_THRESHOLD` for household size 2) — prefer deriving from `RULESET` when practical
5. Run `make test` (includes the knowledge/ruleset spot-check)

Do **not** introduce a third runtime source (CSV/JSON loader, parse-markdown-at-boot) unless a human explicitly asks. Documented dual copy + agent discipline is the chosen POC tradeoff.

### Comments in code and knowledge

Keep cross-references in place:

- `ruleset.py` must cite the public URL **and** `knowledge/nc-fns-income-limits.md`
- `nc-fns-income-limits.md` must cite the public URL **and** `src/eligibility/ruleset.py`

## Other mirrored facts (lighter sync)

Not engine math, but keep consistent when editing:

| Fact                                       | Code                                                     | Knowledge / copy                                                    |
| ------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------- |
| ePASS apply URL                            | `src/safety/checks.py` (`APPLICATION_RESPONSE`)          | `knowledge/nc-fns-how-to-apply.md`, `knowledge/agent-disclaimer.md` |
| Household “buy and prepare food together”  | `src/planner/missing.py` question hints                  | `knowledge/nc-fns-general-requirements.md`                          |
| Student complexity (no full determination) | `src/eligibility/engine.py` student branch               | `knowledge/nc-fns-student-rules.md`                                 |
| 130% vs 200% “which test?”                 | engine caveats + `source_ids` include gross-income-tests | `knowledge/nc-fns-gross-income-tests.md` (RAG only; no 130% math)   |

## Quality bar

- User-facing text: no vendor/key/ops internals (see `src/openai_errors.py`).
- CLI screening card: plain language (`src/cli_display.py`), not backend jargon.
- Imports at module top only (ruff E402 / PLC0415).
- Prefer honest **unable / need more info** over a confident wrong eligibility label.

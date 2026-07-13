# Agent instructions (this repo)

POC NC FNS informal screening agent. Prefer small, correct changes over new infrastructure.

## Architecture (do not regress)

- **Single runtime:** only the agent API runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). CLI and smoke are HTTP clients via `AgentApiClient` / `PUBLIC_BASE_URL`.
- **Hybrid control:** LLM extracts language and composes replies; **code** owns safety, case state, planner, and eligibility math.
- **RAG is citations only:** retrieval must not invent dollar thresholds. Thresholds come from `RULESET` in code.

## Program packs

- Policy data lives under `programs/{slug}/` (rules YAML, knowledge, smoke).
- **`src/` is program-agnostic** infrastructure (pipeline, API, Qdrant, registry).
- Registry: `programs/registry.yaml`. Default slug is first listed pack.
- Sessions pin `program_slug` + `ruleset_id` at create; do not switch program mid-session.
- Qdrant: one collection; every retrieve **pre-filters** by `program_slug` (never post-filter).

## Dual copy of income thresholds (intentional, per pack)

For **nc-fns**, eligibility **math** is `programs/nc-fns/rules/*.yaml`; the **public table** is curated markdown for RAG.

| Role                                | Path                                                                |
| ----------------------------------- | ------------------------------------------------------------------- |
| Rules (authoritative for assessment) | `programs/nc-fns/rules/2025-10.yaml` (and future FY files)          |
| Knowledge (RAG / display table)     | `programs/nc-fns/knowledge/nc-fns-income-limits.md`                 |
| Manifest metadata                   | `programs/nc-fns/knowledge/manifest.json` entry `nc-fns-income-limits` |
| Soft CI guard                       | `tests/test_knowledge.py` (`test_income_doc_matches_ruleset_table`) |

**Public provenance (both copies must stay aligned with this source):**

- Publisher: More In My Basket - Am I Eligible?
- URL: https://morefood.org/using-snap/am-i-eligible/
- Table label: Maximum Gross Monthly Income (**200%**), FY window **2025-10-01 - 2026-09-30**
- Ruleset id: `nc-fns-screening-2025-10`
- Knowledge source id: `nc-fns-income-limits`

### When you change thresholds, dates, or ruleset id

Update **all** of these in the same change:

1. `programs/nc-fns/rules/YYYY-MM.yaml` (table, dates, id, source_id, description)
2. `programs/nc-fns/knowledge/nc-fns-income-limits.md` (table, effective dates, ruleset id line)
3. `programs/nc-fns/knowledge/manifest.json` effective dates / notes if needed
4. Pack smoke expectations under `programs/nc-fns/smoke/` when needed
5. Run `make test` (includes the knowledge/ruleset spot-check)

### Comments in code and knowledge

- Rules YAML must stay dual-copied with the income-limits knowledge doc
- `nc-fns-income-limits.md` must cite the public URL **and** the rules YAML path

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

# Agent instructions (this repo)

POC NC FNS informal screening agent. Prefer small, correct changes over new infrastructure.

## Architecture (do not regress)

- **Single runtime:** only the agent API runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). CLI and smoke are HTTP clients via `AgentApiClient` / `PUBLIC_BASE_URL`.
- **Hybrid control:** LLM extracts language and composes replies; **code** owns safety, case state, planner, and eligibility math.
- **RAG is citations only:** retrieval must not invent dollar thresholds. Dollar math comes from declared requirement modules (e.g. `gross_income_limit` table in rules YAML).
- **Requirement modules:** planner + engine only collect/score what each ruleset lists under `requirements:`. No silent feature flags from “key present.”

## Program packs

- Policy data lives under `programs/{slug}/` (rules YAML, knowledge, smoke).
- **`src/` is program-agnostic** infrastructure (pipeline, API, Qdrant, registry, **requirement modules**).
- Registry: `programs/registry.yaml` lists enabled packs. **No default program** — session create, smoke, and retrieve all require an explicit `program_slug`.
- Second pack `ca-calfresh` is a real public program (California CalFresh / SNAP) for multi-program scale.
- Sessions pin `program_slug` + `ruleset_id` at create; do not switch program mid-session.
- Qdrant: one collection; every retrieve **pre-filters** by `program_slug` (never post-filter).

### How to add a program

1. Create `programs/{slug}/program.yaml` (display name, `search_aliases`, opening message, service area).
2. Add `rules/*.yaml` with `effective_from` / `effective_to` (null = open-ended), `source_id`, optional `supporting_source_ids`, and a non-empty **`requirements`** list (compose existing module types + params).
3. Add `knowledge/manifest.json` + markdown (dual-copy income table when using `gross_income_limit`).
4. Optional `smoke/scenarios.yaml` (+ optional line-oriented script files).
5. Pack-local unit tests under `programs/{slug}/tests/`:
   - `test_rules.py` — metadata, requirements list, thresholds, ruleset resolve
   - `test_knowledge.py` — manifest + dual-copy income table
   - `test_eligibility.py` — screening outcomes for **this** pack’s modules/numbers
   - `test_smoke_pack.py` — scenarios.yaml + script alignment
   Keep **infrastructure** tests in top-level `tests/`.
6. Register the slug in `programs/registry.yaml`.
7. `make index` + `make test` (+ `make smoke PROGRAM={slug}` when live).

### How to add a requirement module type

1. Implement `RequirementModule` under `src/eligibility/modules/` (`validate`, `missing`, `assess`).
2. Register it in `src/eligibility/modules/__init__.py` (`MODULE_REGISTRY`).
3. Reference `type: your_type` from pack rules YAML with validated params.
4. Add unit tests (loader rejects bad params; planner/engine respect declaration).

## Dual copy of income thresholds (intentional, per pack)

For **nc-fns**, eligibility **math** is `programs/nc-fns/rules/*.yaml`; the **public table** is curated markdown for RAG.

| Role                                | Path                                                                |
| ----------------------------------- | ------------------------------------------------------------------- |
| Rules (authoritative for assessment) | `programs/nc-fns/rules/2024-10.yaml`, `2025-10.yaml` (and peers)   |
| Knowledge (RAG / display table)     | `nc-fns-income-limits-2024.md`, `nc-fns-income-limits.md`, etc.     |
| Manifest metadata                   | `programs/nc-fns/knowledge/manifest.json` (per-source effective dates) |
| Soft CI guard                       | `programs/nc-fns/tests/test_knowledge.py` (ruleset ↔ income doc)    |

**Multi-version:** resolve by `as_of` (latest `effective_from` wins); **pin** `ruleset_id` on session create.
Retrieve filters knowledge docs by `as_of` within the program silo so the wrong FY table is not cited.

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

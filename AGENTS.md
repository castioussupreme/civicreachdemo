# Agent instructions (this repo)

POC public-benefits eligibility agent. Prefer small, correct changes over new infrastructure.

## Architecture (do not regress)

- **Single runtime:** only the agent API runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). CLI and smoke are HTTP clients via `AgentApiClient` / `PUBLIC_BASE_URL`.
- **Hybrid control:** LLM extracts and composes; **code** owns safety, case state, planner, eligibility math.
- **RAG is citations only:** retrieval must not invent dollar thresholds. Math comes from declared requirement modules (e.g. `gross_income_limit` tables in rules YAML).
- **Requirement modules:** planner + engine only collect/score what each ruleset lists under `requirements:`.
- **No default program:** session create, smoke, and retrieve require explicit `program_slug`.

## Program packs

Policy data lives under `programs/{slug}/`. `src/` is program-agnostic. Registry: `programs/registry.yaml`. Sessions pin `program_slug` + `ruleset_id` at create. Qdrant: one collection; every retrieve **pre-filters** by `program_slug`.

### Add a program

1. `programs/{slug}/program.yaml` — display name, `search_aliases`, short greeting (`opening_message`), service area, optional `apply_url` / `apply_label` / `apply_channel`.
2. `rules/*.yaml` — `effective_from` / `effective_to`, `source_id`, non-empty **`requirements`** list.
3. `knowledge/manifest.json` + markdown (dual-copy income table when using `gross_income_limit`).
4. Optional `smoke/scenarios.yaml` + script files.
5. Pack tests under `programs/{slug}/tests/` (`test_rules`, `test_knowledge`, `test_eligibility`, `test_smoke_pack`). Infrastructure tests stay in top-level `tests/`.
6. Register slug in `programs/registry.yaml`.
7. `make index` + `make test` (+ `make smoke PROGRAM={slug}` when live).

Opening text is composed as greeting + code-owned scope blurb + continue CTA (`build_opening_message`). Intake waits for `screening_started` (go-ahead or volunteered facts).

**Residency field:** `lives_in_service_area` (never program-specific names). Extraction is a generic benefits slot schema; modules decide what is required.

### Add a requirement module type

1. Implement `RequirementModule` under `src/eligibility/modules/` (`validate`, `missing`, `assess`).
2. Register in `MODULE_REGISTRY` (`modules/__init__.py`).
3. Reference `type: your_type` from pack rules YAML.
4. Unit-test loader + planner/engine behavior.

## Dual copy of income thresholds (intentional)

| Role | Location |
| ---- | -------- |
| Math (authoritative) | `programs/{slug}/rules/*.yaml` |
| RAG / display table | `programs/{slug}/knowledge/*-income-limits*.md` |
| Soft CI guard | pack `tests/test_knowledge.py` |

**When thresholds, dates, or ruleset ids change**, update rules YAML, matching knowledge doc, manifest if needed, and smoke expectations in one change. Run `make test`.

**Example provenance (`nc-fns`):** [More In My Basket – Am I Eligible?](https://morefood.org/using-snap/am-i-eligible/) — Maximum Gross Monthly Income (**200%**), FFY windows in rules/knowledge.

## Quality bar

- User-facing text: program-agnostic where possible (use pack `apply_channel` / apply links). No vendor/key/ops internals.
- CLI screening card: plain language (`src/cli_display.py`).
- Imports at module top only (ruff E402 / PLC0415).
- Prefer honest **unable / need more info** over a confident wrong eligibility label.

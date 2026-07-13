# Public Benefits Eligibility Agent (POC)

Proof-of-concept text agent that helps a resident see whether they **likely qualify for a public benefits program** — multi-turn conversation, grounded answers, structured eligibility logic, and session state.

Not an official determination. No applications, agency contact, or scraping.

Response to the CivicReach **Engineering Case Study** (`Engineering Case Study.md`), which frames the problem as **generic public-benefits eligibility** (any comparable program with public rules). This repo ships **pluggable program packs** under `programs/{slug}/` and uses **NC FNS** (and a second pack, **CalFresh**) as concrete examples of the kind of program the prompt allows — not as the product’s only domain. Sessions require an explicit program (no default).

---

## Quick start

**Prereqs:** [Poetry](https://python-poetry.org/docs/#installation), Docker, Make, `OPENAI_API_KEY`.

```bash
cp .env.example .env   # set OPENAI_API_KEY (chat + embeddings)
make dev               # install + Compose: API, Redis, Qdrant
```

Second terminal (stack stays up):

```bash
make cli               # interactive chat (pick a program, or --program <slug>)
make smoke PROGRAM=nc-fns   # live multi-scenario E2E (PROGRAM required)
```

| Command                 | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `make dev`              | Deps + stack (API / Redis / Qdrant)                  |
| `make up` / `make up-d` | Stack only (foreground / detached)                   |
| `make down`             | Stop Compose                                         |
| `make cli`              | Interactive CLI                                      |
| `make smoke PROGRAM=…`  | Live multi-scenario E2E (OpenAI + Redis + Qdrant)    |
| `make index`            | Resync knowledge embeddings (unchanged docs skipped) |
| `make test`             | Unit tests: `tests/` + `programs/*/tests/`           |
| `make lint`             | ruff + mypy + vulture                                |

| Resource | Where                                                   |
| -------- | ------------------------------------------------------- |
| Health   | `GET …/api/health`                                      |
| Programs | `GET …/api/programs?q=` (typeahead catalog)             |
| OpenAPI  | `…/docs`                                                |
| Chat     | `POST …/api/chat` `{"message":"…","session_id":"…"}`    |
| Session  | `POST …/api/session` · `/api/session/{id}/state\|reset` |
| Redis    | `PUBLIC_REDIS_URL` (printed on launch)                  |
| Qdrant   | `PUBLIC_QDRANT_URL` (printed on launch)                 |

**Runtime path (single source of truth):** only the **agent** container runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). **CLI and smoke are thin HTTP clients** against `PUBLIC_BASE_URL` (written to `.env.runtime` on stack start). They do not call the pipeline or OpenAI on the host.

**Programs:** policy packs live under `programs/{slug}/` (rules YAML, knowledge, smoke). `src/` is reusable infrastructure. Each ruleset declares **`requirements`** (typed modules: residency, household size, gross income limit, optional softeners). The planner and engine only collect and score what is declared — not a fixed SNAP interview. Sessions **pin** a program + ruleset at create (`GET /api/programs?q=` for discovery; CLI type-to-narrow picker). Switching programs means a **new session**. Qdrant is one collection with a **mandatory `program_slug` pre-filter** on every retrieve.

| Pack          | Role                                                                                         |
| ------------- | -------------------------------------------------------------------------------------------- |
| `nc-fns`      | Example program: North Carolina FNS (SNAP) gross screen (rulesets 2024-10 + 2025-10)         |
| `ca-calfresh` | Second example: California CalFresh (SNAP) gross screen (public CDSS / county tables)        |

**Add a program:** see `AGENTS.md` (“How to add a program”).

| Client         | Role                 | Where operator detail lands |
| -------------- | -------------------- | --------------------------- |
| CLI / smoke    | UX + exit codes only | **Agent** Docker logs       |
| REST / OpenAPI | Same API as CLI      | **Agent** Docker logs       |

User-facing failures stay generic (no vendor, keys, or ops commands). Full provider errors are logged only in the agent (`docker compose logs agent` or the `make up` / `make dev` foreground stream). The CLI shell is intentionally quiet so it is not a second log sink.

CLI extras: `/why` screening card; `/debug on` for API debug metadata; `/program` starts a new session for another pack.

**Redis / Qdrant:** if `REDIS_URL` or `QDRANT_URL` is unset, Compose spawns them; if set, those instances are used instead.

No browser UI — CLI for humans, REST/OpenAPI for clients.

---

## What we're testing

Case-study criteria (architectural judgment, guardrails, failure modes, tradeoffs) map to this delivery of a **public benefits eligibility** agent:

### 1. Architectural judgment

**Hybrid stateful agent:** LLM for language and fact extraction; **code** owns workflow, safety, case state, and eligibility math. Retrieval grounds wording and citations; it does **not** compute eligibility.

```text
message
  → safety (code)
  → extract facts (LLM → structured JSON)
  → validate / update case (code)
  → plan missing fields (code)
  → eligibility engine if ready (code + versioned pack ruleset)
  → retrieve policy citations (vector RAG → Qdrant, program silo only)
  → compose reply (LLM, constrained to tool results)
```

| Layer      | Owner | Role                                                    |
| ---------- | ----- | ------------------------------------------------------- |
| Safety     | Code  | Crisis, PII, injection, scope, no-apply                 |
| Extract    | LLM   | Natural language → slots (service area from pack)       |
| Case state | Code  | `EligibilityCase`, contradictions, confidence           |
| Planner    | Code  | Next question; no re-ask of known facts                 |
| Engine     | Code  | Pack ruleset thresholds (pinned `ruleset_id`)           |
| Retrieval  | Code  | Embeddings + Qdrant; citations only; filter by program |
| Compose    | LLM   | Natural reply over structured results                   |

**Sessions:** Redis case keys (~24h sliding TTL). Pipeline is pure `process_turn(message, case) → (reply, case)`, invoked only from the FastAPI agent (not from host CLI). Each case stores `program_slug`, pinned `ruleset_id`, and `as_of`.

**Transcript:** last ~25 turns for wording only; user lines PII-redacted; input and retention share `MAX_MESSAGE_CHARS` (default 1500). Over-long messages get a summarize prompt and are not stored.

### 2. Guardrails

| Risk                              | Behavior                                           |
| --------------------------------- | -------------------------------------------------- |
| Crisis language                   | Stop; 988 / 911                                    |
| Out of scope                      | Refuse; optional 211                               |
| Application / portal automation   | Refuse; static apply pointers from pack knowledge  |
| PII (SSN, address)                | Warn, redact, continue without storing raw PII     |
| Prompt injection                  | Notice; fixed rules; engine still owns eligibility |
| Over-claiming                     | Screening labels only; student softens to unable   |

### 3. Failure modes

| Failure                              | Handling                                                  |
| ------------------------------------ | --------------------------------------------------------- |
| Ambiguous income                     | `UNCERTAIN` + clarify amount / period / gross vs net      |
| Contradiction across turns           | Block assess until confirmed                              |
| Net take-home under limit            | Ask once for approx pre-tax; no tax-bracket reverse math  |
| Net take-home over limit             | Likely ineligible (gross ≥ take-home)                     |
| One-person income in multi-person HH | Ask once for household total; bound if already over limit |
| Student                              | Gross may pass; overall unable without full student rules |
| Outside service area                 | Likely ineligible for that program’s jurisdiction         |
| Model invents thresholds             | Numbers only from assessment / pack ruleset               |
| Redis / Qdrant down                  | Fail fast with start-stack guidance                       |
| OpenAI auth / quota / rate limit     | Generic client reply; full detail only in agent logs      |
| Stack not up while running CLI/smoke | Client error: start `make up-d` / `make dev` first        |

Smoke scripts live under `programs/{slug}/smoke/`.
`make smoke PROGRAM=<slug>` runs that pack’s scenarios via the agent API (no default program).

### 4. Tradeoffs

| Chose                                                   | Cut / deferred                                      | Why                                                                    |
| ------------------------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------- |
| Hybrid control flow                                     | Fully agentic tool loop                             | Predictable; eligibility not model-decided                             |
| Program packs + shared `src/`                           | One hardcoded program in app code                   | Add a pack without forking the pipeline                                |
| Vector RAG (OpenAI embeddings + Qdrant) over curated KB | Full-web / multi-corpus RAG                         | Semantic recall; same API key; expandable without inventing thresholds |
| One Qdrant collection, `program_slug` pre-filter        | Separate DBs per program                            | Isolation without ops sprawl                                           |
| Incremental re-embed by content hash                    | Re-embed entire corpus every boot                   | Low cost; only changed docs re-indexed                                 |
| Gross-income **screen** only                            | Full program rules (net, resources, deductions, …)  | Honest incompleteness; agency decides                                  |
| Dual copy of income table (rules YAML + markdown)       | CSV/JSON loader or parse-doc-at-boot                | See below — OK for LLM-assisted POC                                    |
| CLI + REST as thin clients of one agent API             | Host-side `process_turn` / dual runtime; browser UI | One pipeline & log stream; enough for live review                      |
| Redis sessions + Docker Compose                         | Managed cloud-only infra                            | One-command local demo; optional bring-your-own URLs                   |
| Unit tests with stubbed LLM/RAG                         | Paid live-LLM CI only                               | Fast CI; `make smoke` for live path                                    |

### Income thresholds: dual copy (intentional)

Eligibility **math** needs a typed ruleset; RAG needs a readable public table. Those are two different consumers **inside each pack**:

| Consumer         | Location                                              | Role                                         |
| ---------------- | ----------------------------------------------------- | -------------------------------------------- |
| Engine / planner | `programs/{slug}/rules/*.yaml` (pinned at session)    | Dollar compare, ruleset id, effective window |
| RAG + humans     | `programs/{slug}/knowledge/*-income-limits*.md`       | Citations, explanations, same FY table       |

**Example pack (`nc-fns`):** More In My Basket – [Am I Eligible?](https://morefood.org/using-snap/am-i-eligible/) — Maximum Gross Monthly Income (**200%**), Oct 1, 2025 – Sep 30, 2026. Ruleset id `nc-fns-screening-2025-10`. Prior FFY lives in `rules/2024-10.yaml` + matching knowledge doc.

We **do not** add a boot-time CSV/JSON rules pipeline beyond pack YAML for this POC. Drift risk is real but small:

- Cross-links in rules YAML and the income doc point at each other and at the public URL.
- `tests/test_knowledge.py` spot-checks that ruleset amounts appear in the markdown.
- **Coding agents** follow `AGENTS.md`: any threshold/date/ruleset-id change updates rules, knowledge, and related fixtures in one change.

With LLM-assisted development, that discipline is cheap; a second runtime source of truth is not free.

**In scope:** public-benefits eligibility POC with pluggable program packs (gross screen), guardrails, multi-turn state, curated KB + vector retrieval, CLI + REST, Compose.
**Out of scope:** browser UI, real applications, full case management across agencies, voice, production auth/compliance.

---

## Retrieval (final design)

- **Corpus:** per-pack `programs/{slug}/knowledge/` + `manifest.json` (public excerpts only).
- **Index:** chunk → OpenAI embeddings (`OPENAI_EMBEDDING_MODEL`, default `text-embedding-3-small`) → **Qdrant** collection (`kb_programs`).
- **Sync:** all enabled packs; per-document content hash; skip unchanged sources; delete orphans **within** a pack.
- **Query:** embed user/policy query → cosine top‑k with **`program_slug` pre-filter**; optional `as_of` drops docs outside their effective window; assessment turns prefer engine `source_ids`.
- **Boundary:** RAG supplies snippets and citations for compose; the pack ruleset supplies dollar thresholds and screening status.
- **200% vs 130% (where documented):** math uses only the public 200% table for that pack; pack knowledge can ground “which test?” answers without a second dollar schedule.

---

## Problem solved

| Requirement                            | Delivery                                            |
| -------------------------------------- | --------------------------------------------------- |
| Multi-turn conversation                | Agent API + Redis; CLI/smoke as HTTP clients        |
| Ground in a knowledge base             | Per-pack knowledge + vector retrieve + citations    |
| Structured logic for rules             | Pack rules YAML + `src/eligibility` engine/income   |
| Track state; ask only for missing info | `EligibilityCase` + planner                         |
| Guardrails                             | `src/safety/checks.py`                              |
| Messy / adversarial input              | Injection, PII, ambiguity, contradiction paths      |
| Expand to another program              | New pack under `programs/` + registry entry         |

---

## Layout

```text
src/
  process_turn.py   pipeline (agent only)
  safety/           guardrails
  extraction/       LLM → slots
  state/            case model + updates
  planner/          next question
  eligibility/      engine + income helpers (thresholds from pack rules)
  programs/         registry loader (pack metadata + rulesets)
  retrieval/        chunk, embed, Qdrant, retrieve
  compose/          LLM reply + grounding
  session.py        Redis
  api/              FastAPI (sole production entry to process_turn)
  api_client.py     shared HTTP client
  cli.py            interactive client (no host pipeline)
  smoke.py          live multi-scenario API smoke (pack-driven)
programs/
  registry.yaml     enabled public-benefits program packs (clients pick explicitly)
  nc-fns/           example pack: rules, knowledge, smoke, tests/
  ca-calfresh/      example pack: rules, knowledge, smoke, tests/
tests/              program-agnostic infrastructure tests
AGENTS.md           coding-agent rules (program packs + dual-copy)
```

Rulesets resolve by `as_of` (latest covering version wins) and are **pinned** on session create. Dual-copy tables live with each pack’s knowledge docs. Retrieve filters by `program_slug` and document effective window.

---

## Testing & review

```bash
make test
make lint
make up-d && make smoke PROGRAM=nc-fns   # live (PROGRAM required)
make cli                                 # pick program interactively
```

Prefer honest **unable to determine** / **need more information** over a confident wrong label on novel inputs.

---

## Productionize (not in this POC)

1. Policy service + assessment audit log
2. Human oversight / confidence gates
3. Live eval harness in CI
4. PII / compliance review
5. Auth + rate limits
6. Observability (per-turn traces)
7. KB / ruleset ops (effective dating, dual-run)
8. Retrieval eval set / hybrid re-rankers if the corpus grows a lot
9. Extra channels (voice/SMS)
10. Redis / Qdrant AUTH/TLS
11. Legal review of disclaimers

---

## License / disclaimer

Informal educational POC for a **generic public benefits eligibility** agent (case-study framing). Concrete packs illustrate one domain (food assistance) using public rules only. Sources attributed in each pack’s `programs/{slug}/knowledge/manifest.json`. Not affiliated with NCDHHS, CDSS, USDA, or any county agency.

---

## What would make this scope better

Prioritized for review-meeting impact: correctness → UX → performance, still inside the same product.

### Correctness (highest leverage)

| Improvement                                                 | Why                                        |
| ----------------------------------------------------------- | ------------------------------------------ |
| Short 130% / “which test?” KB note (per pack where relevant)| Stops invention when users push on caveats |
| Effective-period awareness in replies when near FY rollover | Rules tables are dated by fiscal year      |

### User experience (same scope)

| Improvement                                                                 | Why                                              |
| --------------------------------------------------------------------------- | ------------------------------------------------ |
| Progress / known facts in plain language (“I have residency + household…”)  | Multi-turn state becomes visible                 |
| One clear question per turn (already mostly true—tighten compose prompt)    | Less interview fatigue                           |
| After terminal assess: offer next steps (apply links) without re-interviewing | Closes the loop pack apply docs already support |
| Contradiction repair that restates both values simply                       | Messy input is a scored axis                     |
| CLI: less backend residue                                                   | Reviewers are residents, not operators           |
| Optional short “what this screen covers / doesn’t” on first turn            | Sets expectations; reduces over-trust            |

### Performance (only where it matters)

| Improvement                                                     | Why                                                                                                               |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Two LLM calls/turn (extract + compose) is the main cost/latency | Biggest win: merge carefully or skip compose when safety early-exits and when a templated terminal card is enough |
| Retrieve only when useful (policy Q, assess, student)           | Avoid embed+Qdrant every turn if not already gated                                                                |
| Cache embeddings for repeated policy queries in a session       | Cheap                                                                                                             |
| Don’t re-index on every discussion of code                      | Incremental index is already good                                                                                 |
| Redis/Qdrant local Compose                                      | Fine for POC; not a bottleneck vs OpenAI                                                                          |

Avoid “performance” work that doesn’t change demo feel (extra vector DBs, re-rankers, browser UI).

### Guardrails / failure modes (polish, not expand)

| Item                     | Note                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------- |
| Ambiguous “about $2,500” | Already a design focus; worth a dedicated golden path in pack smoke                      |
| Injection                | Keep code ownership of eligibility; maybe one more adversarial line in pack smoke        |
| PII                      | SSN/address handled; watch for phone/email if users dump contact info                    |
| Crisis                   | 988/911 path exists; keep it short and non-eligibility-continuing                        |

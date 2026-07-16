# Public Benefits Eligibility Agent (POC)

Text agent that helps a resident see whether they **likely qualify** for a public benefits program: multi-turn chat, grounded answers, structured eligibility math, and session state.

Not an official determination. No applications, agency contact, or scraping.

Built for the CivicReach [Engineering Case Study](docs/Engineering%20Case%20Study.md) (generic public-benefits eligibility; **NC FNS** and **CalFresh** are example packs, not the product domain). Sessions require an explicit program — **no default**.

**Architecture diagrams (Mermaid):** [docs/architecture.md](docs/architecture.md) — see [how to view](#architecture-diagrams) below.

---

## Quick start

**Prereqs:** [Poetry](https://python-poetry.org/docs/#installation), Docker, Make, `OPENAI_API_KEY`.

```bash
cp .env.example .env   # set OPENAI_API_KEY
make dev               # install + Compose: API, Redis, Qdrant
```

Second terminal:

```bash
make cli                        # pick a program, chat
make smoke PROGRAM=nc-fns       # live multi-scenario E2E (PROGRAM required)
make test                       # unit tests (stubbed LLM)
make lint
```

| Command                              | Purpose                            |
| ------------------------------------ | ---------------------------------- |
| `make dev` / `make up` / `make down` | Stack lifecycle                    |
| `make cli`                           | Interactive client                 |
| `make smoke PROGRAM=…`               | Live E2E via agent API             |
| `make index`                         | Resync knowledge embeddings        |
| `make test` / `make lint`            | Unit tests / ruff + mypy + vulture |

| Resource         |                                          |
| ---------------- | ---------------------------------------- |
| Health / OpenAPI | `GET …/api/health` · `…/docs`            |
| Programs         | `GET …/api/programs?q=`                  |
| Session / chat   | `POST …/api/session` · `POST …/api/chat` |

**Runtime:** only the **agent** container runs `process_turn` (OpenAI, Redis, Qdrant, eligibility). CLI and smoke are HTTP clients against `PUBLIC_BASE_URL` (written to `.env.runtime`). Operator detail lives in agent logs (`docker compose logs agent`), not the CLI.

CLI: `/why` screening card · `/debug on` · `/program` new session for another pack.

---

## Architecture

**Hybrid control:** LLM extracts language and composes replies; **code** owns safety, case state, planner, and eligibility math. Retrieval grounds wording and citations — it does **not** compute thresholds.

```text
message
  → dual safety (LLM confidence primary, narrow regex fallback)
  → extract facts (LLM → structured JSON)
  → validate / update case (code)
  → plan missing fields (code; waits for go-ahead after scope intro)
  → eligibility if ready (code + pinned pack ruleset)
  → retrieve policy citations (Qdrant, program_slug pre-filter)
  → compose reply (LLM, grounded to assessment facts)
```

| Layer          | Owner | Role                                             |
| -------------- | ----- | ------------------------------------------------ |
| Safety         | Code  | Crisis, PII, injection, scope, no-apply          |
| Extract        | LLM   | Natural language → slots                         |
| Case / planner | Code  | `EligibilityCase`, contradictions, next question |
| Engine         | Code  | Declared requirement modules + rules YAML tables |
| Retrieval      | Code  | Embeddings + Qdrant; citations only              |
| Compose        | LLM   | Natural reply; terminal grounding receipt        |

**Program packs** under `programs/{slug}/` (rules, knowledge, smoke, tests). `src/` is program-agnostic. Each ruleset lists **`requirements`** (typed modules). Sessions **pin** `program_slug` + `ruleset_id` at create. One Qdrant collection with mandatory `program_slug` pre-filter.

| Pack          | Role                                             |
| ------------- | ------------------------------------------------ |
| `nc-fns`      | NC Food & Nutrition Services (SNAP) gross screen |
| `ca-calfresh` | California CalFresh (SNAP) gross screen          |

**Opening flow:** first message = greeting + “what this screen covers/doesn’t” + continue CTA. Household/income intake starts only after go-ahead (or volunteered facts). After a terminal result, pack apply links appear once; post-assess turns do not re-interview.

**Extraction model:** program-agnostic public-benefits slots (`lives_in_service_area`, household, income, optional student/elderly flags). Packs declare which modules consume them.

**Live debug:** agent logs one line per turn (`program`, `ruleset`, `stage`, `safety`, `missing`, `assess`). CLI `/debug on` (or `?debug=true`) returns the full structured trace (known facts, plan, extraction, citations).

Add a pack or module type: see `AGENTS.md`.

### Architecture diagrams

Detailed Mermaid diagrams (system context, turn pipeline, hybrid control, session sequence, program packs, eligibility engine, retrieval) live in:

**[docs/architecture.md](docs/architecture.md)**

#### How to view them

Mermaid is plain text inside fenced ` ```mermaid ` blocks. Render it with any of:

| Method                  | Steps                                                                                                                                                                 |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GitHub / GitLab**     | Open [docs/architecture.md](docs/architecture.md) on the remote; diagrams render automatically in the file view and in PRs.                                           |
| **VS Code / Cursor**    | Install a Mermaid preview extension (e.g. “Markdown Preview Mermaid Support”), open `docs/architecture.md`, then **Markdown: Open Preview** (`⌘⇧V` / `Ctrl+Shift+V`). |
| **JetBrains IDEs**      | Open the file; Mermaid in Markdown previews with the bundled or Mermaid plugin.                                                                                       |
| **Mermaid Live Editor** | Copy a single `mermaid` code block into [mermaid.live](https://mermaid.live) for zoom/export (PNG/SVG).                                                               |
| **CLI (optional)**      | `npx -y @mermaid-js/mermaid-cli -i docs/architecture.md -o docs/architecture.pdf` (or per-diagram `.mmd` extracts) if you need a static export.                       |

You do **not** need the agent stack running to view diagrams—only a Markdown+Mermaid renderer.

---

## Decisions & tradeoffs

| Chose                                          | Cut / deferred                                              | Why                                                                                            |
| ---------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Hybrid control flow                            | Fully agentic tool loop                                     | Predictable; eligibility not model-decided                                                     |
| Program packs + shared `src/`                  | One hardcoded program                                       | Add a pack without forking the pipeline                                                        |
| Vector RAG over curated KB                     | Full-web multi-corpus RAG                                   | Semantic recall; no invented thresholds                                                        |
| One Qdrant collection + pre-filter             | Separate DBs per program                                    | Isolation without ops sprawl                                                                   |
| Gross-income **screen** only                   | Full rules (net, resources, deductions, student exemptions) | Honest incompleteness; agency decides                                                          |
| Dual copy: rules YAML + markdown table         | Single parse-at-boot source                                 | Engine needs typed tables; RAG needs readable prose. Drift guarded by pack tests + `AGENTS.md` |
| CLI + REST as thin clients of one API          | Dual runtime / browser UI                                   | One pipeline & log stream; enough for live review                                              |
| Redis sessions + Compose                       | Managed cloud-only                                          | One-command local demo                                                                         |
| Unit tests with stubbed LLM                    | Paid live-LLM CI only                                       | Fast CI; `make smoke` for the live path                                                        |
| Dual safety (LLM ≥0.7 conf, else narrow regex) | Regex-only or LLM-only                                      | Fail closed on crisis/PII phrases; grey scope is semantic                                      |

**In scope:** multi-program eligibility POC (gross screen), guardrails, multi-turn state, curated KB + vector retrieval, CLI + REST, Compose.
**Out of scope:** browser UI, real applications, full case management, voice, production auth/compliance.

---

## Guardrails & failure modes

| Risk                              | Behavior                                                     |
| --------------------------------- | ------------------------------------------------------------ |
| Crisis language                   | Stop; 988 / 911                                              |
| Out of scope / off-topic          | Refuse or steer; resume screening when ready                 |
| Apply-for-me                      | Refuse; pack apply pointers after assess                     |
| PII (SSN, street address)         | Warn, redact, continue without raw PII                       |
| Prompt injection                  | Notice; engine still owns eligibility                        |
| Ambiguous income                  | `UNCERTAIN` + clarify                                        |
| Contradiction across turns        | Block assess until confirmed                                 |
| Net take-home / partial HH income | Ask once; bound when already over limit; no reverse tax math |
| Student                           | Soften to unable without full student rules                  |
| Outside service area              | Likely ineligible for that pack’s jurisdiction               |
| OpenAI / Redis / Qdrant down      | Generic user reply; detail in agent logs                     |

---

## Layout

```text
src/           pipeline, API, modules, retrieval (program-agnostic)
programs/      registry.yaml + {slug}/ (rules, knowledge, smoke, tests)
docs/          architecture diagrams (Mermaid)
tests/         infrastructure unit tests
AGENTS.md      pack/module authoring + dual-copy discipline
```

---

## Productionize (not this POC)

1. Auth, rate limits, Redis/Qdrant TLS
2. Assessment audit log + human oversight gates
3. Live eval harness in CI
4. PII/compliance review; observability (per-turn traces)
5. Rules/KB ops (single source of truth, dual-run effective dating)
6. Legal review of disclaimers

---

## License / disclaimer

Informal educational POC. Packs use public eligibility rules only; sources in each pack’s `knowledge/manifest.json`. Not affiliated with NCDHHS, CDSS, USDA, or any county agency.

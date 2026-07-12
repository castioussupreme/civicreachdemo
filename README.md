# NC FNS Eligibility Agent (POC)

A **text-based, multi-turn** informal screen for **North Carolina Food & Nutrition Services (SNAP)**.
Not an official determination. No applications, agency contact, or scraping.

This repo is a response to the CivicReach **Engineering Case Study** (see `Engineering Case Study.md`).

---

## Quick start

**Prereqs:** [Poetry](https://python-poetry.org/docs/#installation), Docker, Make, and an `OPENAI_API_KEY`.

```bash
cp .env.example .env   # set OPENAI_API_KEY
make dev               # poetry install + Docker Compose (API + Redis)
```

In a **second terminal** (stack must stay up):

```bash
make cli               # interactive chat
make smoke             # live happy-path E2E (real LLM + Redis)
# or scripted demos:
poetry run python -m src.cli --script scripts/happy_path.txt
poetry run python -m src.cli --script scripts/adversarial.txt
```

| Command                 | What it does                                 |
| ----------------------- | -------------------------------------------- |
| `make dev`              | Install deps + start API/Redis               |
| `make up` / `make up-d` | Start stack only (foreground / detached)     |
| `make down`             | Stop Compose                                 |
| `make cli`              | Interactive CLI (needs Redis from the stack) |
| `make smoke`            | Live happy-path E2E (OpenAI + Redis)         |
| `make test`             | Pytest (deterministic unit tests)            |
| `make lint`             | ruff + mypy + vulture                        |

**CLI tips:** chat normally; after a result use `/why` for the code-owned screening card. `/debug on` shows stage/extract metadata.

| Resource    | Where                                                |
| ----------- | ---------------------------------------------------- |
| **Health**  | `GET …/api/health`                                   |
| **OpenAPI** | `…/docs`                                             |
| **Chat**    | `POST …/api/chat` `{"message":"…","session_id":"…"}` |
| **Session** | `POST …/api/session` · `/api/session/{id}/state`     |
| **Redis**   | Printed by `make dev` as `PUBLIC_REDIS_URL`          |

No browser UI — CLI for live review, REST/OpenAPI for scripted clients.

**Redis:** optional `REDIS_URL` in `.env`. If unset, Compose **spawns** Redis. If set, that instance is used and no Redis container starts.

---

## What we're testing

The case study evaluates four things more than feature volume. Mapping of **criteria → evidence in this repo**:

### 1. Architectural judgment for AI agent design

**Choice:** a **hybrid stateful agent** — LLM for language + fact extraction; **code owns** workflow, safety, case state, and eligibility math.

```text
message
  → safety (code)
  → extract facts (LLM → structured JSON)
  → validate / update case (code)
  → plan missing fields (code)
  → eligibility engine if ready (code + versioned ruleset)
  → retrieve policy citations (keyword RAG over curated KB)
  → compose reply (LLM, constrained to tool results)
```

| Layer      | Owner | Why                                                      |
| ---------- | ----- | -------------------------------------------------------- |
| Safety     | Code  | Deterministic crisis / PII / injection / scope           |
| Extract    | LLM   | Messy natural language → slots                           |
| Case state | Code  | `EligibilityCase` slots, contradictions, confidence      |
| Planner    | Code  | One next question; never re-ask known facts              |
| Engine     | Code  | Versioned ruleset `nc-fns-screening-2025-10`             |
| Retrieval  | Code  | Curated markdown + citations; **RAG does not calculate** |
| Compose    | LLM   | Warm reply; rolling history for wording only             |

**Case state vs sessions**

1. **Pipeline** — `process_turn(message, case) → (reply, case)` is pure of I/O.
2. **Sessions** — Redis `fns:case:{id}` with a **24h sliding TTL** (refreshed on every write). Expiry deletes slots + transcript + assessment together. Idle sessions are gone; `get` after expiry starts fresh.
3. **Transcript** — last ~25 turns for *wording continuity* only; user lines are **PII-redacted** before storage. **Input and retention share `MAX_MESSAGE_CHARS`** (default 1500, env-overridable). Over-long user messages get a friendly “please summarize” reply and are **not** stored.

This is deliberate: eligibility must not depend on the model “remembering” thresholds or inventing math.

**Conversational UX:** intake replies stay short and human (no “Need more information” labels). A soft disclaimer is injected at most once, on a real screening conclusion. Stage / extract / plan details show with CLI `/debug on` or API `?debug=true`.

### 2. Guardrail thinking

| Risk                                         | Behavior                                                                  |
| -------------------------------------------- | ------------------------------------------------------------------------- |
| Crisis / self-harm language                  | Stop screening; 988 / 911 pointers (`src/safety/checks.py`)               |
| Out of scope (other benefits, legal/medical) | Refuse; optional 211 pointer                                              |
| Application / ePASS automation               | Explicit refuse; static “how to apply” pointers only                      |
| PII (SSN, street address)                    | Warn, redact before extract, continue without storing raw PII             |
| Prompt injection                             | Notice; continue under fixed rules; engine still owns eligibility         |
| Over-claiming eligibility                    | Disclaimer always; labels are _screening_ only; students soften to unable |

Guardrails run **before** extraction. Application refusal can still continue if the same message also answers eligibility questions.

### 3. Failure-mode reasoning

| Failure mode                                 | Handling                                                                  |
| -------------------------------------------- | ------------------------------------------------------------------------- |
| Ambiguous income (“about $2,500”)            | Lower confidence → `UNCERTAIN`; planner asks period / gross vs net        |
| Self-contradiction across turns              | `Contradiction` on case; block assess until user confirms                 |
| Net-only or individual income (multi-person) | Engine returns **unable to determine**, not a false pass/fail             |
| College student                              | Even if gross screen passes → **unable to determine** + student caveat    |
| Not NC resident                              | **Likely ineligible** for _NC_ FNS without collecting full income         |
| LLM invents a threshold                      | Compose prompt forbids inventing rules; numbers come only from assessment |
| LLM down / bad JSON                          | Extract path fails hard (no silent mock); operator sees API/CLI error     |
| Redis down                                   | CLI/API fail fast with “start `make dev`” guidance                        |

Demo scripts: `scripts/happy_path.txt`, `scripts/adversarial.txt`, full matrix in `scripts/demo-scenarios.md`.

### 4. Reasoning about tradeoffs

| Chose                                    | Cut / deferred                                      | Why (POC horizon)                                   |
| ---------------------------------------- | --------------------------------------------------- | --------------------------------------------------- |
| Hybrid control flow                      | Fully agentic tool-calling loop                     | Predictable review; eligibility not model-decided   |
| Keyword RAG over small curated KB        | Embeddings / vector DB                              | Corpus is tiny; citations must be inspectable       |
| Redis-only sessions                      | In-memory / browser FE                              | Multi-process CLI+API; production-shaped boundary   |
| CLI + REST                               | Web chat UI                                         | Case study allows CLI; less surface, same live demo |
| Gross-income **screen** only             | Full SNAP (net, resources, deductions, categorical) | Honest about incompleteness; DSS still decides      |
| Stubbed LLM in unit tests                | Paid live-LLM CI eval                               | Fast, free CI; live demos for review meeting        |
| Optional external Redis or spawned Redis | Always-managed cloud Redis                          | One-command local demo vs bring-your-own            |

**Scope in:** NC FNS gross screen, guardrails, multi-turn state, curated KB, CLI + REST, Docker Compose.
**Scope out:** browser UI, real applications, multi-program, voice, production auth/compliance.

---

## Problem solved (must-haves)

| Case-study requirement                         | Status | Where                                          |
| ---------------------------------------------- | ------ | ---------------------------------------------- |
| Multi-turn text conversation                   | Yes    | CLI / `POST /api/chat` + Redis case            |
| Ground answers in a knowledge base             | Yes    | `knowledge/` + `src/retrieval/kb.py`           |
| Tools / structured logic for rules             | Yes    | `src/eligibility/{ruleset,engine,income}.py`   |
| Track state; ask only for what is still needed | Yes    | `EligibilityCase` + `src/planner/missing.py`   |
| Guardrails (scope, crisis, PII)                | Yes    | `src/safety/checks.py`                         |
| Adversarial / messy input                      | Yes    | injection, PII, ambiguity, contradiction paths |

---

## Architecture (detail)

```text
src/
  process_turn.py     fixed pipeline orchestration
  safety/             crisis, PII, injection, scope
  extraction/         LLM → structured slots
  state/              EligibilityCase + apply_validated_updates
  planner/            missing fields / next question
  eligibility/        versioned thresholds + assessment
  retrieval/          curated KB citations
  compose/            constrained natural-language reply
  session.py          Redis store
  api/                FastAPI
  cli.py              interactive + --script demos
knowledge/            public excerpts + manifest.json
```

**Ruleset** `nc-fns-screening-2025-10` encodes public gross monthly limits (FY 2026 table in `knowledge/nc-fns-income-limits.md`). **RAG cites policy; it does not calculate eligibility.**

---

## Testing & review prep

```bash
make test    # ~107 unit tests; LLM stubbed — free, deterministic
make lint
```

| Layer             | Coverage idea                                               |
| ----------------- | ----------------------------------------------------------- |
| Domain            | Income normalize, thresholds, student/net/individual paths  |
| Safety            | Crisis, injection, SSN, application, out-of-scope           |
| State / planner   | Contradictions, multi-fact, missing-field order             |
| Pipeline          | Happy path + adversarial turns with stubbed extract/compose |
| API / CLI / Redis | Session create/chat/reset; CLI error paths                  |

**Live review** (needs `OPENAI_API_KEY` + `make dev`):

```bash
make cli
# or
poetry run python -m src.cli --script scripts/happy_path.txt
poetry run python -m src.cli --script scripts/adversarial.txt
```

Expect reviewers to try inputs you have not scripted. Prefer honest **unable to determine** / **need more information** over a confident wrong label.

---

## Layout

`Makefile` · `pyproject.toml` + `poetry.lock` · `start.py` (Compose helper) · `src/` · `knowledge/` · `compose.yaml` · `Dockerfile` · `scripts/` · `tests/`

---

## Productionize (intentionally not in this POC)

1. Policy service + audit log of assessments
2. Human oversight / confidence gates
3. Live eval harness in CI (golden dialogues + LLM-as-judge)
4. PII / compliance review
5. Auth + rate limits
6. Observability (traces per turn: extract, plan, assess)
7. KB / ruleset ops (effective dating, dual-run)
8. Extra channels (voice/SMS)
9. Redis AUTH/TLS
10. Legal review of disclaimers

---

## License / disclaimer

Informal educational POC. Public policy excerpts are attributed in `knowledge/manifest.json`. Not affiliated with NCDHHS or DSS.

# NC FNS Eligibility Agent (POC)

Informal multi-turn screen for **NC Food & Nutrition Services (SNAP)**. Not an official determination. No applications, agency contact, or scraping.

## Quick start (`pnpm dev` equivalent)

**Prereqs:** [Poetry](https://python-poetry.org/docs/#installation), Docker, Make.

```bash
cp .env.example .env   # set OPENAI_API_KEY
make dev               # poetry install + Docker Compose (API + Redis)
```

That installs host Python deps and starts the stack. URLs/ports are printed on launch.

| Command                 | What it does                                |
| ----------------------- | ------------------------------------------- |
| `make dev`              | Install deps + start API/Redis (default)    |
| `make install`          | Poetry install only (`.venv`)               |
| `make up` / `make up-d` | Start stack (foreground / detached)         |
| `make down`             | Stop Compose                                |
| `make cli`              | Interactive CLI (uses Redis from the stack) |
| `make test`             | Pytest                                      |
| `make hooks`            | Install pre-commit hooks                    |
| `make lint`             | ruff + mypy + vulture                       |

**Tooling:** one `pyproject.toml` (Poetry reads it) + `poetry.lock`. No separate package config. `start.py` is only the Compose launcher (ports/Redis); use **`make dev`**, not a bare `./start`.

### CLI (terminal chat)

```bash
# Terminal 1 — stack (API + Redis)
make dev
# or: make up-d

# Terminal 2 — interactive chat (not a GUI window)
make cli
```

Scripted demo:

```bash
poetry run python -m src.cli --script scripts/happy_path.txt
```

### API

| Resource       | How to find it                                                 |
| -------------- | -------------------------------------------------------------- |
| **API health** | `GET …/api/health`                                             |
| **OpenAPI**    | `…/docs`                                                       |
| **Chat**       | `POST …/api/chat` `{"message":"…","session_id":"…"}`           |
| **Session**    | `POST …/api/session` · state/reset under `/api/session/{id}/…` |
| **Redis**      | Printed by `make dev` (`PUBLIC_REDIS_URL`)                     |

No browser frontend — CLI for humans, REST/OpenAPI for samples.

**Redis:** optional `REDIS_URL` in `.env`. If unset, Compose **spawns** Redis. If set, that instance is used and no Redis container starts.

## Architecture

**Hybrid stateful agent:** LLM for language + fact extraction; **code** owns workflow, safety, case state, and eligibility math. **RAG cites policy; it does not calculate eligibility.**

```text
message → safety → extract (LLM) → validate/update case → missing fields
        → eligibility engine (if ready) → retrieve citations → compose (LLM)
```

| Layer      | Role                                           |
| ---------- | ---------------------------------------------- |
| Safety     | Crisis, PII, injection, out-of-scope, no-apply |
| Extract    | ≤1 LLM call → structured slots                 |
| Case state | `EligibilityCase` slots                        |
| Planner    | Next question / ready-to-assess                |
| Engine     | Versioned ruleset `nc-fns-screening-2025-10`   |
| Retrieval  | Curated markdown + citations                   |
| Compose    | LLM response over tool results only            |

### Case state vs session storage

1. **Pipeline** — `process_turn(message, case) → (reply, case)`; no storage inside the pipeline.
2. **Sessions** — Redis maps `session_id → EligibilityCase` (`fns:case:{id}`, ~24h TTL). Spawned by default via `make dev`, or bring your own with `REDIS_URL`.

## Scope

**In:** NC FNS gross screen, guardrails, CLI + REST API, Docker Compose.
**Out:** browser UI, full SNAP determination, multi-program, voice, real applications.

## Layout

`Makefile` · `pyproject.toml` + `poetry.lock` · `start.py` (Compose helper) · `src/` · `knowledge/` · `compose.yaml` · `Dockerfile`

## Productionize (next)

1. Policy service + audit log
2. Human oversight / confidence gates
3. Eval harness in CI
4. PII / compliance
5. Auth + rate limits
6. Observability
7. KB / ruleset ops
8. Extra channels (voice/SMS)
9. Redis AUTH/TLS
10. Legal review of disclaimers

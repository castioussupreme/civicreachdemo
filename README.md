# NC FNS Eligibility Agent (POC)

Informal multi-turn screen for **NC Food & Nutrition Services (SNAP)**. Not an official determination. No applications, agency contact, or scraping.

## Run

```bash
./setup-hooks && pre-commit run --all-files   # host quality hooks
```

## Architecture

**Hybrid stateful agent:** LLM for language + fact extraction; **code** owns workflow, safety, case state, and eligibility math. **RAG cites policy; it does not calculate eligibility.**

```text
message → safety → extract (LLM) → validate/update case → missing fields
        → eligibility engine (if ready) → retrieve citations → compose (LLM)
```

| Layer      | Role                                                                          |
| ---------- | ----------------------------------------------------------------------------- |
| Safety     | Crisis, PII, injection, out-of-scope, no-apply                                |
| Extract    | ≤1 LLM call → structured slots                                                |
| Case state | In-process `EligibilityCase` (`unknown \| known \| uncertain \| conflicting`) |
| Planner    | Code decides next question / ready-to-assess                                  |
| Engine     | Pure functions + versioned ruleset `nc-fns-screening-2025-10`                 |
| Retrieval  | Curated markdown + citations                                                  |
| Compose    | ≤1 LLM call over tool results only                                            |

**Rejected:** RAG-first chat; pure form FSM; dual free-running agents.

### Case state vs session storage

Two different things:

1. **Case state (this agent pipeline)** — An `EligibilityCase` object holds slots (residency, household size, income, …) for **one conversation**.
   `process_turn(message, case) → (reply, updated case)` is **stateless storage-wise**: the caller passes the case in and gets it back. Nothing is written to disk or Redis inside the pipeline.

2. **Session storage (interfaces / Docker)** — A thin store maps `session_id → EligibilityCase` so multi-turn works over HTTP or CLI:

   | Backend    | When                       | Where data lives                             |
   | ---------- | -------------------------- | -------------------------------------------- |
   | **Memory** | CLI / single-process tests | Python dict in the process (gone on restart) |
   | **Redis**  | Docker Compose default     | Key `fns:case:{id}`, JSON, ~24h TTL          |

   No SQL/JDBC database. No permanent case archive. Redis is optional durability/sharing for the web API, not a case-management system.

## Scope

**In:** NC residency, household size, gross income screen, student uncertainty, contradictions, guardrails, citations, web UI + API.

**Out:** net/resources/ABAWD, immigration deep-dive, multi-program, voice, submit apps.

## Guardrails & failure modes

| Risk                 | Handling                    |
| -------------------- | --------------------------- |
| Crisis               | 988/911; stop screen        |
| PII                  | Don’t ask; redact           |
| Injection            | Immutable ruleset/code path |
| Submit app           | Refuse; ePASS pointer only  |
| Ambiguous income     | Clarify period/gross        |
| Contradiction        | Reconfirm before assess     |
| Student / borderline | `unable_to_determine`       |

# NC FNS Eligibility Agent (POC)

Informal multi-turn screen for **NC Food & Nutrition Services (SNAP)**. Not an official determination. No applications, agency contact, or scraping.

## Architecture

**Hybrid stateful agent:** LLM for language + fact extraction; **code** owns workflow, safety, state, and eligibility math. **RAG cites policy; it does not calculate eligibility.**

```text
message → safety → extract (LLM) → validate/update state → missing fields
        → eligibility engine (if ready) → retrieve citations → compose (LLM)
```

| Layer     | Role                                                              |
| --------- | ----------------------------------------------------------------- |
| Safety    | Crisis, PII, injection, out-of-scope, no-apply                    |
| Extract   | ≤1 LLM call → structured slots                                    |
| State     | `unknown \| known \| uncertain \| conflicting` (Redis in Compose) |
| Planner   | Code decides next question / ready-to-assess                      |
| Engine    | Pure functions + versioned ruleset `nc-fns-screening-2025-10`     |
| Retrieval | Curated markdown + citations                                      |
| Compose   | ≤1 LLM call (or template) over tool results only                  |

**Rejected:** RAG-first chat; pure form FSM; dual free-running agents.

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

# Architecture

This document describes the **hybrid-control** design of the public-benefits eligibility agent: the LLM extracts language and composes replies; **code** owns safety, case state, planning, and eligibility math. Retrieval grounds wording and citations — it does **not** invent dollar thresholds.

> **How to view these diagrams:** see [README → Architecture diagrams](../README.md#architecture-diagrams).

---

## 1. System context (who talks to what)

Only the **agent API** runs the LLM, Redis, Qdrant, and eligibility engine. CLI and smoke are thin HTTP clients.

```mermaid
flowchart TB
    subgraph clients [Clients — no LLM]
        CLI["CLI<br/>make cli"]
        SMOKE["Smoke runner<br/>make smoke PROGRAM=…"]
        HTTP["Any HTTP client<br/>OpenAPI /docs"]
    end

    subgraph stack [Docker Compose stack]
        API["Agent API<br/>FastAPI · process_turn"]
        REDIS[(Redis<br/>sessions)]
        QDR[(Qdrant<br/>one collection)]
    end

    subgraph external [External]
        OAI["OpenAI<br/>chat + embeddings"]
    end

    subgraph packs [Program packs on disk]
        REG["programs/registry.yaml"]
        NC["programs/nc-fns/"]
        CA["programs/ca-calfresh/"]
    end

    CLI -->|PUBLIC_BASE_URL| API
    SMOKE -->|PUBLIC_BASE_URL| API
    HTTP --> API
    API <--> REDIS
    API <--> QDR
    API <--> OAI
    API --> REG
    API --> NC
    API --> CA
    QDR -.->|indexed from| NC
    QDR -.->|indexed from| CA
```

---

## 2. Single-turn pipeline (`process_turn`)

Fixed control flow. The model never chooses the next tool or decides eligibility status.

```mermaid
flowchart TD
    MSG[User message] --> LEN{Length OK?}
    LEN -->|no| LONG[Reply: message too long]
    LEN -->|yes| EXT["1. Extract<br/>LLM → facts + safety signals JSON"]

    EXT -->|OpenAI error| FB["Regex-only safety fallback"]
    EXT --> SAFE
    FB --> SAFE

    SAFE["2. Dual safety resolve<br/>LLM conf ≥ 0.7 wins, else narrow regex"]

    SAFE -->|crisis| CRISIS["Stop · 988 / 911<br/>no eligibility"]
    SAFE -->|refuse apply without facts| APP["Refuse apply + next screening hint"]
    SAFE -->|steer / PII / injection / continue| UPD

    UPD["3. Validate + update EligibilityCase<br/>code: types, contradictions, income normalize"]
    UPD --> GO{Screening started?<br/>go-ahead or volunteered facts}
    GO -->|no| INTRO["Stay in introduction<br/>scope already in opening"]
    GO -->|yes| PLAN

    PLAN["4. Planner<br/>missing fields from declared modules only"]
    PLAN -->|open contradiction| CLAR["Ask confirm conflict"]
    PLAN -->|missing slots| ASK["Next question hint"]
    PLAN -->|ready| ENG

    ENG["5. Eligibility engine<br/>run requirements in ruleset order"]
    ENG --> RAG["6. Retrieve citations<br/>Qdrant · mandatory program_slug filter"]
    RAG --> COMP
    CLAR --> COMP
    ASK --> COMP
    INTRO --> COMP
    APP --> COMP

    COMP["7. Compose reply<br/>LLM + grounding receipt on terminal assess"]
    COMP --> OUT["Reply · safety_action · stage<br/>assessment? · citations? · debug?"]
```

### Safety priority (first match wins)

```mermaid
flowchart LR
    A[crisis] --> B[refuse_application]
    B --> C[refuse_scope]
    C --> D[steer_off_topic]
    D --> E[injection_notice]
    E --> F[pii_warn]
    F --> G[continue]
```

---

## 3. Hybrid control (who owns what)

```mermaid
flowchart LR
    subgraph llm [LLM-owned]
        E["Extract<br/>natural language → slots"]
        C["Compose<br/>natural English reply"]
    end

    subgraph code [Code-owned]
        S[Safety resolution]
        ST["Case state<br/>EligibilityCase"]
        P[Planner]
        M["Requirement modules"]
        R["Rules YAML tables<br/>authoritative $"]
        V["Vector retrieve<br/>citations only"]
        G["Grounding receipt<br/>must match assessment"]
    end

    E --> S
    E --> ST
    ST --> P
    P --> M
    M --> R
    M --> C
    V --> C
    C --> G
    G -->|mismatch| T["Template fallback<br/>never invent numbers"]
```

| Concern                       | Owner                        | Must not                            |
| ----------------------------- | ---------------------------- | ----------------------------------- |
| Dollar thresholds / pass-fail | Code + rules YAML            | Come from RAG or free-form LLM math |
| Crisis / PII / injection      | Code (dual with LLM signals) | Be silently ignored                 |
| Next question                 | Planner from modules         | Be a free-form agent tool loop      |
| Citations                     | Qdrant retrieve              | Change the assessment status        |

---

## 4. Session lifecycle

```mermaid
sequenceDiagram
    participant U as User / CLI
    participant API as Agent API
    participant R as Redis
    participant L as OpenAI
    participant Q as Qdrant
    participant Disk as programs/{slug}

    U->>API: POST /api/session {program_slug}
    API->>Disk: load program + resolve ruleset as_of
    API->>R: store EligibilityCase (pin program_slug, ruleset_id)
    API-->>U: opening_message (greeting + scope + CTA)

    loop each turn
        U->>API: POST /api/chat {session_id, message}
        API->>R: load case
        API->>L: extract JSON
        API->>API: safety → update → plan → maybe assess
        opt ready to assess
            API->>Disk: pinned ruleset modules
            API->>Q: retrieve(program_slug=…)
            API->>L: compose + grounding receipt
        end
        API->>R: save case
        API-->>U: reply, assessment?, citations?
    end
```

---

## 5. Program packs (multi-program without forking `src/`)

`src/` is program-agnostic. Policy, knowledge, and smoke live under `programs/{slug}/`.

```mermaid
flowchart TB
    REG["programs/registry.yaml<br/>slug list"] --> PACK["programs/{slug}/"]

    PACK --> PY["program.yaml<br/>display name, service area,<br/>opening, apply_url"]
    PACK --> RULES["rules/*.yaml<br/>effective window, requirements"]
    PACK --> KNOW["knowledge/<br/>manifest.json + markdown"]
    PACK --> SMK["smoke/<br/>scenarios.yaml + scripts"]
    PACK --> TST["tests/<br/>pack-local pytest"]

    RULES --> REQ["requirements:<br/>type: residency<br/>type: household_size<br/>type: gross_income_limit<br/>type: student_soft_unable?<br/>type: elderly_disabled_caveat?"]

    REQ --> MOD["src/eligibility/modules/*<br/>MODULE_REGISTRY"]
    KNOW --> IDX["make index → embed → Qdrant<br/>payload.program_slug"]
    MOD --> ENG["calculate_eligibility"]
    ENG --> ASSESS["Assessment status + reasons + caveats"]
```

### Dual copy of income thresholds (intentional)

```mermaid
flowchart LR
    PUB["Public source<br/>e.g. More In My Basket / COLA"] --> YAML["rules/*.yaml<br/>MATH — authoritative"]
    PUB --> MD["knowledge/*-income-limits*.md<br/>RAG / display table"]
    YAML --> ENG["Eligibility engine"]
    MD --> RAG["Qdrant citations"]
    YAML -.->|pack tests guard drift| MD
```

---

## 6. Eligibility engine (declare-driven)

Only modules listed on the **pinned** ruleset run. Soft modules may still annotate after a hard fail (e.g. student / elderly caveats).

```mermaid
flowchart TD
    CASE[EligibilityCase] --> LOOP[For each requirement in ruleset order]
    LOOP --> MOD[module.assess case, spec]
    MOD -->|NEED_MORE| NMI[NEEDS_MORE_INFORMATION]
    MOD -->|FAIL| FAIL[had_fail]
    MOD -->|UNABLE| UNB[had_unable]
    MOD -->|PASS / SKIP| NEXT[Next module]
    FAIL --> SOFT{Soft module remaining?}
    SOFT -->|yes| MOD
    SOFT -->|no| OUT
    UNB --> NEXT
    NEXT --> LOOP
    LOOP -->|done| OUT{Aggregate}
    OUT -->|had_fail| INEL[LIKELY_INELIGIBLE]
    OUT -->|had_unable| UND[UNABLE_TO_DETERMINE]
    OUT -->|else| ELIG[LIKELY_ELIGIBLE]
```

Built-in module types:

| Type                      | Role                                                            |
| ------------------------- | --------------------------------------------------------------- |
| `residency`               | Service-area hard fail                                          |
| `household_size`          | Collect / require size                                          |
| `gross_income_limit`      | Table-driven gross monthly screen; net / individual soft bounds |
| `student_soft_unable`     | Soften income pass → unable when student (no full exemptions)   |
| `elderly_disabled_caveat` | Caveat only; never flips status                                 |

---

## 7. Retrieval silo

One Qdrant collection; every query **must** pre-filter by `program_slug` so packs never cross-contaminate.

```mermaid
flowchart LR
    Q[Query text] --> EMB[OpenAI embed]
    EMB --> S["Qdrant search<br/>filter: program_slug = session pack"]
    S --> OPT{source_ids?}
    OPT -->|assessment grounding| PREF[Prefer ruleset source_ids first]
    OPT -->|policy question| TOP[Top-k semantic hits]
    PREF --> CITE[Citation list]
    TOP --> CITE
    CITE --> COMP[Compose prompt only]
```

---

## 8. Repo layout (mental map)

```mermaid
flowchart TB
    ROOT[civicreachdemo]
    ROOT --> SRC["src/<br/>pipeline, API, modules, retrieval"]
    ROOT --> PROG["programs/<br/>packs + registry"]
    ROOT --> DOCS["docs/<br/>architecture diagrams"]
    ROOT --> TESTS["tests/<br/>infrastructure unit tests"]
    ROOT --> AGENTS["AGENTS.md<br/>pack / module authoring"]
    ROOT --> CS["Engineering Case Study.md<br/>original brief"]

    SRC --> PT[process_turn.py]
    SRC --> API[api/]
    SRC --> ELIG[eligibility/]
    SRC --> RET[retrieval/]
    SRC --> SAFE[safety/]
    SRC --> STATE[state/]
```

---

## Related

- [README](../README.md) — quick start, tradeoffs, guardrails
- [Engineering Case Study](Engineering%20Case%20Study.md) — original brief
- [AGENTS.md](../AGENTS.md) — how to add a pack or module type

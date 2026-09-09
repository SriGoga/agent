# Architecture Overview

## Two systems that compose

1. **The URL Shortener** (`src/url_shortener/`) -- the target service. FastAPI + SQLite.
2. **The orchestrator** (`src/orchestrator/`) -- a hand-rolled DAG execution engine that
   drives the shortener's SDLC (requirements -> design -> implementation -> testing ->
   documentation -> release) through staged, gated, auditable nodes. This is the piece the
   assignment calls the "critical differentiator," and it's designed to be usable on its own
   (see `src/scenarios/demo.json`), independent of the shortener.

```
                     ┌───────────────────────────────────────────┐
                     │              src/orchestrator/             │
                     │                                             │
  scenario graph ──▶ │  engine.py (DAG execution loop)             │
  (JSON, Phase 2)     │    │                                        │
                     │    ├─▶ registry.py  (action name -> Python fn)│
                     │    ├─▶ policy.py    (entry/exit guardrails)  │
                     │    ├─▶ store.py     (state.json + events.jsonl)
                     │    └─▶ metrics.py   (success rate, MTTR, ...) │
                     │                                             │
                     │  cli.py: run / status / approve / replan /  │
                     │           report                             │
                     └──────────────────┬──────────────────────────┘
                                         │ step functions call into
                                         ▼
                     ┌───────────────────────────────────────────┐
                     │           src/url_shortener/                │
                     │  main.py (FastAPI routes)                   │
                     │  storage.py (SQLite repository)             │
                     │  codegen.py / privacy.py / ratelimit.py     │
                     └───────────────────────────────────────────┘
```

`src/scenarios/*_steps.py` is the seam between the two: it registers, per scenario, which
Python function each graph node's `action` name resolves to. Those functions verify and gate
the already-written shortener code (route/schema introspection, a real storage round-trip,
running the actual pytest suites) the same way a CI/CD pipeline gates an existing codebase --
they do not generate code from nothing. This design choice is documented explicitly in
`src/scenarios/greenfield_steps.py`'s module docstring and repeated in each subsequent steps
module, because it's the thing most likely to be misread as "the orchestrator should be
writing the code live."

## Orchestration model

- **Graph**: nodes + `depends_on` edges, loaded from JSON (`src/scenarios/*.json`, authored
  in Phase 2). See `docs/decomposition.md` for the schema and the greenfield graph's diagram.
- **Execution**: each loop iteration computes the *ready set* (nodes whose dependencies all
  passed) and runs it concurrently via `asyncio.gather` -- parallel branches and their joins
  fall out of the graph shape itself, not a separate scheduler.
- **Governance**: policy guardrails (`policy.py`) run as entry/exit gates independent of how
  a graph was authored; human-approval nodes pause the entire run until `approve()`/`reject`;
  a safe-stop circuit breaker halts further dispatch after too many failures; bounded retry
  and rollback handle transient vs. permanent node failure differently.
- **Lineage**: every state transition is an append-only `LineageEvent` (`store.py`), giving
  an audit trail of what ran, when, with what result, and -- for approvals and replans -- who
  decided and why.
- **Re-planning**: `Orchestrator.replan(node_id, reason)` invalidates a node and everything
  transitively downstream, so an upstream spec/schema change doesn't require restarting the
  whole graph. Demonstrated for real (not just in a unit test) in Phase 5.

Full design writeup: `docs/orchestrator.md`.

## Control flow: one node's life cycle

```
PENDING --(deps satisfied)--> [entry policies] --(requires_approval?)--> NEEDS_APPROVAL
                                     │                                        │
                                     │ no                                approve()/reject()
                                     ▼                                        │
                                  RUNNING --(step succeeds)--> [exit policies] --> PASSED
                                     │                                        │
                                     │ step raises                    reject -> ROLLED_BACK
                                     ▼                                        │
                          retry (bounded) --exhausted--> FAILED --(rollback_action?)--> ROLLED_BACK
                                                              │
                                                              ▼
                                          transitive dependents --> SKIPPED
```

## Key decisions (see the linked doc for the full reasoning)

| Decision | Doc |
|---|---|
| SQLite, no real auth, soft-delete/soft-expire, raw-events analytics | `docs/requirements.md` (assumptions A1-A6) |
| Hand-rolled DAG engine instead of an existing workflow framework | This doc + `docs/orchestrator.md` |
| Schema migrations happen in-place (`PRAGMA table_info` guard + `ALTER TABLE`), not via a fresh database | `docs/brownfield-analysis.md` |
| No cross-owner data exposure, enforced by policy, not just by the route's `owner_id` parameter | `docs/ambiguous-analysis.md` |
| Scenario steps verify/gate existing code rather than generate it | This doc, above |

## Data flow: a single "create -> redirect -> analytics" round trip

```
client -> POST /links -> validate (models.py) -> rate limit check -> collision-safe code gen
        -> LinkRepository.create_link() -> SQLite `links` table
client -> GET /{code}  -> LinkRepository.get_link() -> expiry check -> hash_ip(client IP)
        -> LinkRepository.record_click() -> SQLite `clicks` table -> 307 redirect
client -> GET /links/{code}/analytics -> LinkRepository.analytics() (aggregates `clicks`
        on read) -> click_count / unique_visitors / unique_visitors_last_24h / referrers
```

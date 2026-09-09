# Final Engineering Summary

## Plan and rationale

The assignment's actual subject is the orchestration layer, not the URL Shortener -- the
brief calls it the "critical differentiator" and grades depth of decomposition/orchestration
above raw feature count. The plan followed from that: build the orchestrator's core engine
(Phase 3) before the shortener's endpoints exist, prove it on a synthetic graph
(`src/scenarios/demo.json`), and only then use it to actually build, extend, and gate the
target service -- so the orchestrator is exercised for real, not bolted on afterward as a
thin wrapper around already-finished code.

Each phase (see `README.md`'s Phase Log for the full list with PR links) shipped as its own
branch -> PR -> merge, matching how a real team would review incremental SDLC stages rather
than one undifferentiated drop:

0. Project scaffold -> 1. Requirements (normalize the ambiguous prompt) -> 2. Decomposition
(the task graph as data) -> 3. The orchestration engine itself -> 4. Greenfield build (the
graph executed against real code for the first time) -> 5. Brownfield change (a real schema
migration + a real re-planning demonstration) -> 6. Ambiguous scenario (an underspecified ask,
resolved and the resolution enforced by policy) -> 7. Validation and risk control (an audit
that found and fixed two real bugs) -> 8. This document.

## Artifacts

| Artifact | What it is |
|---|---|
| `src/orchestrator/` | The DAG execution engine: models, registry, policy, store, engine, metrics, CLI |
| `src/url_shortener/` | The target service: FastAPI app, SQLite storage, codegen, privacy (IP hashing), rate limiting |
| `src/scenarios/*.json` + `*_steps.py` | The three required scenarios (greenfield/brownfield/ambiguous) as executable graphs, each with real step implementations |
| `tests/` | 54 tests across unit/integration/orchestrator layers (see `docs/testing.md`) |
| `docs/requirements.md` | Requirement understanding + 6 identified ambiguities (A1-A6) |
| `docs/decomposition.md` | Task decomposition: node schema + the greenfield graph's dependency structure |
| `docs/orchestrator.md` | Orchestration engine design writeup |
| `docs/architecture.md` | Component/control-flow overview tying the two systems together |
| `docs/brownfield-analysis.md` | Codebase reasoning for the Phase 5 change |
| `docs/ambiguous-analysis.md` | Ambiguity resolution (B1-B5) for the Phase 6 feature |
| `docs/risks.md` | Consolidated risk register, including two bugs found and fixed during development |
| `docs/api.md` | Endpoint reference |
| `docs/setup.md` | How to install, run, and exercise every part of this |
| `docs/testing.md` | Testing approach, what's covered, what's deliberately not |

## Risks, trade-offs, and validation

Full detail in `docs/risks.md`. Summary: the two real, found-during-development risks (a
SQLite connection leak breaking Windows temp-dir cleanup, found twice in two different call
sites; a TOCTOU race on code creation; unbounded test-execution time in orchestrator steps)
were each fixed with a regression test that fails without the fix. The remaining risks (no
real auth, in-memory rate limiting, no run-state file locking, unbounded lineage log growth,
a fixed policy guardrail set) are documented trade-offs accepted for a 2-3 day prototype, not
oversights -- each has a stated mitigation or an explicit "not implemented, here's why."

## Assumptions

The full list with rationale is `docs/requirements.md`'s assumption table (A1-A6): no real
auth (caller-asserted `owner_id`), reject rather than silently overwrite on alias collision,
raw click events aggregated on read, soft-expire (not hard-delete) so analytics survive
expiry, SQLite as the storage engine, and "reliability" operationalized as collision-safe
codes + rate limiting + idempotent create + orchestrator-level retry/rollback. Two more were
added along the way: `docs/brownfield-analysis.md`'s decision to hash (never store raw) the
client IP, and `docs/ambiguous-analysis.md`'s decision to scope `top_links` to one owner,
never a global cross-owner view.

## Limitations

- No real authentication/authorization system (assumption A1) -- `owner_id` is caller-
  asserted throughout.
- Single-process assumptions: the rate limiter is in-memory, and concurrent orchestrator CLI
  invocations against the same `run_id` are not locked against each other.
- No CI pipeline wired up; validation is local `pytest` runs plus manual CLI walkthroughs of
  each scenario graph, recorded in each phase's PR description.
- No load/concurrency testing tool; the one known race condition is tested by simulating it
  deterministically, not by inducing it under real concurrent load.
- The orchestrator's policy guardrail set (4 policies: schema-change approval, pre-release
  test gating, secret-pattern scanning, cross-owner data exposure) addresses the specific
  risks this project identified -- it is not a general-purpose security scanner.
- No frontend/UI; this is an API-only prototype, evaluated via `pytest`, `curl`/`Invoke-RestMethod`,
  and the orchestrator CLI rather than a browser.

# agent

Agentic SDLC orchestration system with a URL Shortener as the target service.

Built phase by phase (see git history / merged PRs), each phase covering one stage of the
SDLC: requirements, decomposition, orchestration engine, implementation, scenarios, testing,
validation, and documentation.

## Stack

- Python 3.11+
- FastAPI + Uvicorn (URL Shortener API)
- SQLite (storage)
- pytest + httpx (tests)
- A hand-rolled DAG orchestration engine (no external workflow framework) under `src/orchestrator/`

## Layout

```
src/orchestrator/    orchestration engine: graph, execution, gates, policy, lineage store
src/url_shortener/   the target service: API, storage, analytics
src/scenarios/       greenfield / brownfield / ambiguous scenario graphs + step implementations
docs/                requirements, architecture, risks, setup, final engineering summary
tests/               pytest suite
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

See `docs/setup.md` for full run instructions (running the API server, running each
orchestrator scenario via the CLI, troubleshooting).

## Documentation index

| Doc | Covers |
|---|---|
| [`docs/requirements.md`](docs/requirements.md) | Requirement understanding + identified ambiguities (Phase 1) |
| [`docs/decomposition.md`](docs/decomposition.md) | Task decomposition: the greenfield dependency graph (Phase 2) |
| [`docs/orchestrator.md`](docs/orchestrator.md) | Orchestration engine design (Phase 3) |
| [`docs/architecture.md`](docs/architecture.md) | Component/control-flow overview, key decisions (Phase 8) |
| [`docs/api.md`](docs/api.md) | Endpoint reference |
| [`docs/brownfield-analysis.md`](docs/brownfield-analysis.md) | Codebase reasoning for the brownfield change (Phase 5) |
| [`docs/ambiguous-analysis.md`](docs/ambiguous-analysis.md) | Ambiguity resolution for the ambiguous scenario (Phase 6) |
| [`docs/risks.md`](docs/risks.md) | Risk register, including bugs found and fixed (Phase 7) |
| [`docs/setup.md`](docs/setup.md) | Install, run, troubleshoot (Phase 8) |
| [`docs/testing.md`](docs/testing.md) | Testing approach, coverage, limitations, trade-offs (Phase 8) |
| [`docs/final-summary.md`](docs/final-summary.md) | Plan/rationale, artifacts, risks, assumptions, limitations (Phase 8) |

## Phase log

Each phase is one branch -> one PR -> one merge to `main` (see the repo's Closed PRs for the
full diffs). This table is updated as part of every phase's own commit.

| Phase | PR | What landed |
|---|---|---|
| 0 - Project setup | [#1](https://github.com/SriGoga/agent/pull/1) | Python toolchain (`pyproject.toml`), `src/orchestrator`, `src/url_shortener`, `src/scenarios` package skeletons, pytest wired up |
| 1 - Requirement understanding | [#2](https://github.com/SriGoga/agent/pull/2) | `docs/requirements.md`: normalized F1-F6/N1-N4 spec + 6 identified ambiguities with the assumption chosen for each |
| 2 - Task decomposition | [#3](https://github.com/SriGoga/agent/pull/3) | `src/scenarios/greenfield.json` (the 11-node DAG) + `docs/decomposition.md` (node schema, mermaid diagram, parallel/sequential/join call-outs) |
| 3 - Orchestration engine | [#4](https://github.com/SriGoga/agent/pull/4) | `src/orchestrator/`: DAG execution engine (parallel+join, bounded retry, rollback + skip propagation, human-approval pause/resume/reject, policy guardrails, safe-stop, re-planning, lineage log, metrics), CLI, 12 tests |
| 4 - URL Shortener (greenfield) | [#5](https://github.com/SriGoga/agent/pull/5) | `src/url_shortener/`: FastAPI service (create/redirect/analytics/list/delete), SQLite storage, collision-safe codes, rate limiting, idempotency; `src/scenarios/greenfield_steps.py` wires the Phase 2 graph to the real codebase so it can be executed by the orchestrator; `docs/api.md`; 22 new tests |
| 5 - Brownfield: unique-visitor analytics | [#6](https://github.com/SriGoga/agent/pull/6) | `docs/brownfield-analysis.md` (codebase reasoning: impacted modules/APIs/data flows); adds `clicks.ip_hash` with an in-place migration for pre-existing databases, hashed (never raw) visitor IPs (`privacy.py`); `unique_visitors`/`unique_visitors_last_24h` on the analytics endpoint; `src/scenarios/brownfield.json` + `brownfield_steps.py`; 9 new tests including a hand-built pre-migration database; demonstrates the orchestrator's `replan()` for real against this codebase when the analytics spec was refined mid-flight |
| 6 - Ambiguous: "show the most popular links" | [#7](https://github.com/SriGoga/agent/pull/7) | `docs/ambiguous-analysis.md` resolves 5 ambiguities (metric/window/limit/expired-link handling/scope); the one that matters is B5 -- rejecting a global cross-owner leaderboard as a privacy risk given no real auth. That rejection is enforced by a new orchestrator policy (`no_cross_owner_data_exposure`), not just written down. `GET /links/top`; `src/scenarios/ambiguous.json` + `ambiguous_steps.py` (its `spike-scope-decision` node proves the rejected design is actually blocked, not just discouraged); 8 new tests |
| 7 - Validation & risk control | [#8](https://github.com/SriGoga/agent/pull/8) | `docs/risks.md`: consolidated risk register (service-level + orchestrator-level). Found and fixed 2 real gaps during the audit: a TOCTOU race between `code_exists()` and the insert (now `CodeAlreadyExistsError` -> clean 409/503 instead of an unhandled 500), and unbounded test-execution time in scenario steps (`run_pytest()` now takes a timeout, default 60s). 5 new tests |
| 8 - Architecture, setup, testing, final summary | [#9](https://github.com/SriGoga/agent/pull/9) | `docs/architecture.md` (components, control flow, key-decision index), `docs/setup.md` (install/run/troubleshoot), `docs/testing.md` (approach, coverage, what's deliberately not tested), `docs/final-summary.md` (plan/rationale, artifact list, risks, assumptions, limitations) - the remaining assignment deliverables. Documentation only, no code changes; full suite re-verified at 54/54 |


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

See `docs/setup.md` (added in a later phase) for full run instructions once the API and
orchestrator CLI exist.

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


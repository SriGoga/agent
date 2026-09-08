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

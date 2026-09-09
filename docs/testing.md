# Testing Approach, Limitations, and Trade-offs

## Approach

Three layers, matching the two systems in `docs/architecture.md`:

1. **Unit tests** -- pure functions/classes in isolation: `test_codegen.py` (collision-safe
   generation), `test_privacy.py` (IP hashing), `test_scenarios_common.py` (the pytest-runner
   timeout helper), and the storage-level tests inside `test_url_shortener.py` /
   `test_brownfield_unique_visitors.py` that hit `LinkRepository` directly, no HTTP involved.
2. **Integration tests** -- the FastAPI app via `TestClient`, exercising real routing,
   validation, and dependency injection end-to-end: `test_url_shortener.py`,
   `test_brownfield_unique_visitors.py`, `test_top_links.py`.
3. **Orchestrator/engine tests** -- `test_orchestrator.py` exercises the engine itself
   (parallel+join ordering, retry, rollback, approval pause/resume/reject, policy blocking,
   safe-stop, re-planning) against synthetic graphs built inline, independent of the real
   shortener. `test_greenfield_scenario.py` is the one test that runs a *real* scenario graph
   through the *real* engine against the *real* codebase end-to-end -- the integration point
   between all three layers.

Every regression test added while building (the two connection leaks in Phases 4/5, the
TOCTOU race and timeout gaps in Phase 7) was added *because* something actually failed first,
not written speculatively -- see `docs/risks.md`'s "found and fixed" table.

## Running the suite

```
pytest            # all tests
pytest -v         # verbose, one line per test
pytest tests/test_orchestrator.py   # just the engine
```

54 tests as of Phase 7 (see `README.md`'s Phase Log for how that number grew phase by phase).
No test relies on the other tests' side effects: fixtures use `tmp_path` for a fresh SQLite
file and `pytest`'s per-test isolation for orchestrator runs.

## What is deliberately NOT tested

- **Load/concurrency testing.** The TOCTOU race in `docs/risks.md` is tested by simulating
  the race deterministically (monkeypatching `code_exists`), not by actually firing
  concurrent requests and hoping to hit the window. No load-testing tool (locust, k6, etc.)
  is wired up.
- **Multi-process/multi-instance behavior.** The rate limiter and orchestrator run-state
  locking risks (`docs/risks.md`) are both single-process assumptions; nothing tests what
  happens across multiple instances, because nothing in the current design supports it yet.
- **A live browser or UI.** This is an API-only prototype (no frontend), so there is nothing
  to click-test.
- **CI pipeline.** No GitHub Actions / other CI config runs `pytest` automatically on push;
  tests are run locally (and, as shown throughout the phase log, manually via the CLI against
  each scenario graph) as part of each phase's own validation before merging.

## Trade-offs

- Tests that shell out to a real `pytest` subprocess (the orchestrator's testing-stage nodes)
  are slower and more end-to-end than a mock would be, but they are what actually catches a
  regression in the shortener's own suite -- the whole point of Phase 4's design choice that
  orchestrator steps verify real code rather than simulate success.
- Some tests reach into "private" API (`repo._session()` in a couple of tests, to backdate a
  click's timestamp for the 24h-window boundary tests) rather than adding a public method
  whose only purpose would be test setup. Accepted as a minor layering compromise, isolated
  to test files.

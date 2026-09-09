# Validation and Risk Control

Consolidated risk register for the whole system: service-level risks, orchestrator-level
risks, and the guardrails or trade-offs chosen for each. Scenario-specific ambiguities
already resolved elsewhere are referenced, not repeated: see `docs/requirements.md`
(assumptions A1-A6), `docs/brownfield-analysis.md` (schema migration), and
`docs/ambiguous-analysis.md` (ambiguities B1-B5).

## Found and fixed during development (not hypothetical -- these actually happened)

| Risk | Where it surfaced | Fix |
|---|---|---|
| Leaked SQLite connections (`with conn:` manages the transaction, not the handle) | Phase 4's `implement-storage` orchestrator node failed with a Windows file-lock error cleaning up a temp dir | `LinkRepository._session()` context manager explicitly closes every connection (`src/url_shortener/storage.py`) |
| Same leak, different call site | Phase 5's own verification step (`design_schema_change`) hit the identical Windows file-lock error | explicit `try/finally: check_conn.close()` |
| **TOCTOU race on code creation**: `code_exists()` check and the `INSERT` are not atomic | Found during this phase's audit, not a real incident | `create_link()` catches `sqlite3.IntegrityError` and raises `CodeAlreadyExistsError`; the API maps it to `409` (alias race) or `503` (random-code race, please retry) instead of an unhandled `500` |
| **Unbounded test execution time**: a scenario step running the real pytest suite had no timeout | Found during this phase's audit | `run_pytest()` (`src/scenarios/_common.py`) now takes a `timeout` (default 60s) and raises a clean, retryable error instead of hanging a node forever |

## Service-level risks and trade-offs

| Risk | Severity | Mitigation / accepted trade-off |
|---|---|---|
| No real authentication -- `owner_id` is caller-asserted (assumption A1) | High in a real deployment | Explicitly out of scope for this prototype; every ownership-scoped endpoint (list/analytics/delete/top-links) is at least consistent about *which* identifier it trusts, and the ambiguous-scenario policy guardrail (`no_cross_owner_data_exposure`) stops the worst failure mode (cross-owner data leaking through an aggregate endpoint) even without real auth |
| Rate limiter is in-memory, per-process (`ratelimit.py`) | Medium | Fine for this single-process prototype; a multi-instance deployment needs a shared store (Redis) -- noted in the module docstring, not silently ignored |
| IP-hash salt (`privacy.py`) defaults to a hardcoded dev value | Medium (privacy) | Must be overridden via `URL_SHORTENER_IP_SALT` in any real deployment; using the default in production would make the hash crackable via rainbow table against known IP ranges |
| SQLite single-file storage, no replication | Medium (availability) | Accepted for a prototype (assumption A5); repository interface (`LinkRepository`) isolates this so swapping engines later doesn't touch API code |
| Soft-delete/soft-expire retain data indefinitely -- no purge policy | Low | Deliberate (assumption A4: analytics on expired/deleted links stay queryable); a real deployment would need a retention policy, not implemented here |
| `custom_alias`/`owner_id` accept any non-empty string, including e.g. all-whitespace | Low | Not hardened; listed here rather than silently assumed fine |

## Orchestrator-level risks and trade-offs

| Risk | Severity | Mitigation / accepted trade-off |
|---|---|---|
| Two CLI invocations against the same `run_id` concurrently could race on `state.json`/`events.jsonl` | Medium | No file locking implemented; acceptable for a single-operator prototype, called out rather than assumed away. A real deployment would need a lock (or a single-writer process) per run |
| `safe_stop_threshold` is fixed at construction (default 3), not configurable via the CLI | Low | Deliberately simple; exposing it as a `run` flag would be a small, low-risk follow-up if needed |
| Policy guardrails (`policy.py`) are a fixed, named list (3 entries: schema-change approval, pre-release tests, secret-pattern scanning) plus 1 more added in Phase 6 (cross-owner exposure) | Medium | Not an exhaustive security scanner -- it catches the specific failure modes this project identified, not every possible one. New scenarios should ask "does this need a new guardrail?" the way Phase 6 did |
| A node's rollback_action is best-effort logging for source-code changes (`_log_only_rollback` in the scenario step modules) | Low | Real code changes are rolled back with `git revert`, not at runtime; the lineage log records that a rollback was triggered and why, which is the audit trail that matters here |
| Lineage log (`events.jsonl`) grows unbounded per run, never rotated or pruned | Low | Fine at prototype scale; a long-lived deployment would need retention/rotation |

## Validation performed (what actually proves these guardrails work)

- Every "found and fixed" row above has a regression test (see `tests/test_url_shortener.py`,
  `tests/test_scenarios_common.py`) that fails without the fix and passes with it.
- Every policy guardrail has a positive and a negative test
  (`tests/test_orchestrator.py::test_policy_blocks_unapproved_schema_change`,
  `test_policy_blocks_cross_owner_data_exposure`, `test_policy_allows_single_owner_data`).
- The migration risk (Phase 5) is tested against a hand-built pre-existing database, not a
  fresh one (`tests/test_brownfield_unique_visitors.py`).
- `pytest`: 54/54 passing as of this phase.

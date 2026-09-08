# Orchestration Engine

This is the "critical differentiator" component: a hand-rolled DAG execution engine
(`src/orchestrator/`) that runs an SDLC task graph (`src/scenarios/*.json`, from Phase 2)
with governance, not a linear script. No external workflow framework is used, so every
behavior below is engine code that can be read and tested directly.

## Components

| Module | Responsibility |
|---|---|
| `models.py` | `GraphSpec`/`NodeSpec` (the graph), `NodeRuntime` (per-node live state), `LineageEvent` (one audit record) |
| `registry.py` | Maps an `action`/`rollback_action` name from the graph JSON to a Python step function -- graph data never embeds code |
| `policy.py` | Guardrails: entry gates (run before a node) and exit gates (run on a node's output), independent of what the graph author declared |
| `store.py` | Persists run state (`state.json`) and an append-only lineage log (`events.jsonl`) per run under `.orchestrator/runs/<run_id>/` |
| `engine.py` | The `Orchestrator` class: the execution loop, retry/rollback, approval pause/resume, safe-stop, re-planning |
| `metrics.py` | Derives reliability metrics from the lineage log |
| `cli.py` | `run` / `status` / `approve` / `replan` / `report` subcommands |

## Execution model

Each loop iteration:
1. If any node is `needs_approval`, the run **pauses** (`PAUSED_FOR_APPROVAL`) and persists —
   nothing proceeds until a human calls `approve()`.
2. Otherwise, compute the **ready set**: every `pending` node whose `depends_on` are all
   `passed`. Nodes with unrelated dependencies naturally end up in the same ready set and are
   executed concurrently via `asyncio.gather` — this is what gives sequential *and* parallel
   paths with synchronization, from the graph shape alone, no separate scheduler config.
3. A node that fails after exhausting its bounded retries runs its `rollback_action` (if any)
   and every node transitively downstream of it is marked `skipped` — failure propagates
   forward through the graph rather than leaving orphaned nodes stuck `pending` forever.
4. A **safe-stop** circuit breaker (`safe_stop_threshold`) halts the run once enough nodes
   have failed in the graph. It stops *further* dispatch, not already in-flight nodes in the
   same batch (see `tests/test_orchestrator.py::test_safe_stop_halts_before_next_batch`, where
   node `d`'s dependency already passed but it never even starts because the run halted
   before the next batch was computed).

## Governance: policy guardrails

Policies run independent of graph authoring, so a badly-written graph can't opt out:

- **Change control** — `require_approval_on_schema_changes`: any node touching "schema" in
  its id/action must have `requires_approval: true`, or the node is blocked outright.
- **Compliance** — `require_tests_before_release`: a `release`-stage node cannot run until
  every `testing`-stage node in the graph has passed.
- **Security** — `no_plaintext_secrets_in_output`: scans a node's produced output for
  hardcoded-secret patterns (passwords, API keys, PEM private keys, AWS access key ids)
  before accepting it.

## Human approval and decision lineage

A node with `requires_approval: true` stops the run at that point. `Orchestrator.approve()`
records who decided, what they decided, and why (`approval_reason`) as both engine state and
a `LineageEvent` — decision lineage is queryable after the fact via `report`/`status`, not
just implied by a merged PR.

## Dynamic re-planning

`Orchestrator.replan(node_id, reason)` resets that node and every transitive dependent back
to `pending`, so the next `run()` re-executes them. This is how an upstream spec change (e.g.
a revised schema) invalidates everything built on top of it without restarting the whole
graph from scratch. Demonstrated in Phase 5 (brownfield) where a schema-affecting fix
re-triggers the API and test nodes built on it.

## Reliability metrics

`metrics.compute_metrics()` reduces a run's `events.jsonl` to: `success_rate`, `retry_count`,
`rollback_count`, `safe_stop_count`, `mttr_seconds` (mean time from a node's first failed
attempt to its eventual pass), and `end_to_end_latency_seconds`. See `orchestrator report`.

## Try it

```
pip install -e ".[dev]"
python -m orchestrator.cli run --graph src/scenarios/demo.json
# -> pauses at approval-gate
python -m orchestrator.cli approve --run-id <id> --node approval-gate --approver alice --reason "ship it"
python -m orchestrator.cli report --run-id <id>
```

`src/scenarios/demo.json` is a self-contained walkthrough (parallel branches, a node that
fails once then succeeds on retry, a human-approval release gate) independent of the real
URL Shortener scenarios, so the engine can be exercised on its own before Phase 4 exists.

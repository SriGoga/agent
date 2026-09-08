"""Tests for the orchestration engine: parallel execution + joins, bounded retry,
rollback + downstream skip propagation, human-approval pause/resume/reject, policy
guardrails, the safe-stop circuit breaker, dynamic re-planning, and derived metrics."""
from __future__ import annotations

import asyncio

from orchestrator.engine import Orchestrator, new_run_id
from orchestrator.metrics import compute_metrics
from orchestrator.models import GraphSpec, NodeState, RunStatus
from orchestrator.registry import ActionRegistry, StepContext
from orchestrator.store import LineageStore


def make_graph(nodes: list[dict]) -> GraphSpec:
    return GraphSpec.from_dict({"name": "test-graph", "description": "", "nodes": nodes})


def node(id, depends_on=None, action="noop", requires_approval=False, retry=None, rollback_action=None, stage="implementation"):
    return {
        "id": id,
        "stage": stage,
        "description": id,
        "depends_on": depends_on or [],
        "action": action,
        "requires_approval": requires_approval,
        "retry": retry or {"max_attempts": 1, "backoff_seconds": 0},
        "rollback_action": rollback_action,
    }


def new_store(tmp_path, run_id=None) -> LineageStore:
    return LineageStore(run_id or new_run_id(), root=tmp_path)


async def noop(ctx: StepContext) -> dict:
    return {"node": ctx.node_id}


# ---------------------------------------------------------------------------
def test_parallel_execution_and_join(tmp_path):
    graph = make_graph(
        [
            node("root"),
            node("a", depends_on=["root"]),
            node("b", depends_on=["root"]),
            node("join", depends_on=["a", "b"]),
        ]
    )
    registry = ActionRegistry()
    registry.register_action("noop", noop)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])
    status = asyncio.run(orch.run())

    assert status == RunStatus.COMPLETED
    for n in ("root", "a", "b", "join"):
        assert orch.node_states[n].state == NodeState.PASSED

    events = orch.store.read_events()
    started_ts = {e["node_id"]: e["ts"] for e in events if e["event"] == "started"}
    passed_ts = {e["node_id"]: e["ts"] for e in events if e["event"] == "passed"}
    # join must not start until both a and b have passed
    assert started_ts["join"] >= passed_ts["a"]
    assert started_ts["join"] >= passed_ts["b"]


def test_retry_then_success(tmp_path):
    async def flaky(ctx: StepContext) -> dict:
        if ctx.attempt < 2:
            raise RuntimeError("transient")
        return {"ok": True}

    graph = make_graph([node("flaky", action="flaky", retry={"max_attempts": 3, "backoff_seconds": 0})])
    registry = ActionRegistry()
    registry.register_action("flaky", flaky)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])
    status = asyncio.run(orch.run())

    assert status == RunStatus.COMPLETED
    assert orch.node_states["flaky"].state == NodeState.PASSED
    assert orch.node_states["flaky"].attempts == 2
    events = [e["event"] for e in orch.store.read_events()]
    assert "retrying" in events


def test_retry_exhaustion_rolls_back_and_skips_downstream(tmp_path):
    rollback_calls = []

    async def always_fails(ctx: StepContext) -> dict:
        raise RuntimeError("permanent failure")

    async def revert(ctx: StepContext) -> dict:
        rollback_calls.append(ctx.node_id)
        return {}

    graph = make_graph(
        [
            node("bad", action="always_fails", retry={"max_attempts": 2, "backoff_seconds": 0}, rollback_action="revert"),
            node("downstream", depends_on=["bad"]),
        ]
    )
    registry = ActionRegistry()
    registry.register_action("always_fails", always_fails)
    registry.register_action("noop", noop)
    registry.register_rollback("revert", revert)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])
    status = asyncio.run(orch.run())

    assert status == RunStatus.FAILED
    assert orch.node_states["bad"].state == NodeState.ROLLED_BACK
    assert orch.node_states["downstream"].state == NodeState.SKIPPED
    assert rollback_calls == ["bad"]


def test_human_approval_pause_then_approve_resumes(tmp_path):
    graph = make_graph(
        [
            node("gate", requires_approval=True, stage="release"),
            node("after", depends_on=["gate"]),
        ]
    )
    registry = ActionRegistry()
    registry.register_action("noop", noop)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])

    status = asyncio.run(orch.run())
    assert status == RunStatus.PAUSED_FOR_APPROVAL
    assert orch.node_states["gate"].state == NodeState.NEEDS_APPROVAL

    orch.approve("gate", approved=True, approver="alice", reason="looks good")
    status = asyncio.run(orch.run())

    assert status == RunStatus.COMPLETED
    assert orch.node_states["gate"].state == NodeState.PASSED
    assert orch.node_states["after"].state == NodeState.PASSED
    events = orch.store.read_events()
    assert any(e["event"] == "approved" and "alice" in e["detail"] for e in events)


def test_human_approval_rejection_propagates_skip(tmp_path):
    graph = make_graph(
        [
            node("gate", requires_approval=True, stage="release"),
            node("after", depends_on=["gate"]),
        ]
    )
    registry = ActionRegistry()
    registry.register_action("noop", noop)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])

    asyncio.run(orch.run())
    orch.approve("gate", approved=False, approver="bob", reason="not ready")
    status = asyncio.run(orch.run())

    assert status == RunStatus.FAILED
    assert orch.node_states["gate"].state == NodeState.ROLLED_BACK
    assert orch.node_states["after"].state == NodeState.SKIPPED


def test_policy_blocks_unapproved_schema_change(tmp_path):
    graph = make_graph([node("design-schema-change", requires_approval=False)])
    registry = ActionRegistry()
    registry.register_action("noop", noop)
    orch = Orchestrator(graph, registry, new_store(tmp_path))  # default policies active
    status = asyncio.run(orch.run())

    assert status == RunStatus.FAILED
    rt = orch.node_states["design-schema-change"]
    assert rt.state == NodeState.FAILED
    assert "require_approval_on_schema_changes" in rt.error


def test_safe_stop_halts_before_next_batch(tmp_path):
    async def always_fails(ctx: StepContext) -> dict:
        raise RuntimeError("boom")

    graph = make_graph(
        [
            node("z"),
            node("a", action="always_fails", retry={"max_attempts": 1, "backoff_seconds": 0}),
            node("b", action="always_fails", retry={"max_attempts": 1, "backoff_seconds": 0}),
            node("d", depends_on=["z"]),
        ]
    )
    registry = ActionRegistry()
    registry.register_action("noop", noop)
    registry.register_action("always_fails", always_fails)
    orch = Orchestrator(
        graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[], safe_stop_threshold=2
    )
    status = asyncio.run(orch.run())

    assert status == RunStatus.SAFE_STOPPED
    assert orch.node_states["z"].state == NodeState.PASSED
    assert orch.node_states["a"].state == NodeState.FAILED
    assert orch.node_states["b"].state == NodeState.FAILED
    # d's dependency (z) already passed, but the run halted before the next batch dispatched it
    assert orch.node_states["d"].state == NodeState.PENDING


def test_replan_reexecutes_node_and_downstream(tmp_path):
    calls = {"root": 0}

    async def counted_root(ctx: StepContext) -> dict:
        calls["root"] += 1
        return {"count": calls["root"]}

    graph = make_graph([node("root", action="counted_root"), node("child", depends_on=["root"])])
    registry = ActionRegistry()
    registry.register_action("counted_root", counted_root)
    registry.register_action("noop", noop)
    orch = Orchestrator(graph, registry, new_store(tmp_path), entry_policies=[], exit_policies=[])

    status = asyncio.run(orch.run())
    assert status == RunStatus.COMPLETED
    assert calls["root"] == 1

    orch.replan("root", reason="upstream spec changed")
    assert orch.node_states["root"].state == NodeState.PENDING
    assert orch.node_states["child"].state == NodeState.PENDING

    status = asyncio.run(orch.run())
    assert status == RunStatus.COMPLETED
    assert calls["root"] == 2  # actually re-executed, not just re-marked
    assert orch.node_states["child"].state == NodeState.PASSED


def test_transitive_dependents():
    graph = make_graph([node("a"), node("b", depends_on=["a"]), node("c", depends_on=["b"]), node("d")])
    assert graph.transitive_dependents("a") == {"b", "c"}
    assert graph.transitive_dependents("d") == set()


def test_compute_metrics_on_synthetic_events():
    events = [
        {"ts": 0.0, "node_id": "x", "event": "started", "attempt": 1},
        {"ts": 1.0, "node_id": "x", "event": "failed_attempt", "attempt": 1},
        {"ts": 1.0, "node_id": "x", "event": "retrying", "attempt": 1},
        {"ts": 2.0, "node_id": "x", "event": "passed", "attempt": 2},
        {"ts": 2.0, "node_id": "y", "event": "started", "attempt": 1},
        {"ts": 3.0, "node_id": "y", "event": "passed", "attempt": 1},
    ]
    metrics = compute_metrics(events)
    assert metrics["total_nodes"] == 2
    assert metrics["passed_nodes"] == 2
    assert metrics["success_rate"] == 1.0
    assert metrics["retry_count"] == 1
    assert metrics["mttr_seconds"] == 1.0
    assert metrics["end_to_end_latency_seconds"] == 3.0


def test_compute_metrics_empty():
    assert compute_metrics([])["success_rate"] == 0.0

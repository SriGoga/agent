"""Ties Phase 2 (the greenfield graph), Phase 3 (the engine), and Phase 4 (the real service)
together: runs the actual greenfield.json graph through the orchestrator and confirms it
verifies the real codebase end to end, pausing at the human-approval release gate."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orchestrator.engine import Orchestrator, new_run_id
from orchestrator.metrics import compute_metrics
from orchestrator.models import GraphSpec, NodeState, RunStatus
from orchestrator.store import LineageStore
from scenarios.greenfield_steps import build_registry

GRAPH_PATH = Path(__file__).resolve().parents[1] / "src" / "scenarios" / "greenfield.json"


def test_greenfield_graph_runs_end_to_end_through_real_codebase(tmp_path):
    graph = GraphSpec.from_dict(json.loads(GRAPH_PATH.read_text(encoding="utf-8")))
    registry = build_registry()
    store = LineageStore(new_run_id(), root=tmp_path)
    orch = Orchestrator(graph, registry, store)

    # First pause: design-schema requires approval (Phase 3's change-control policy forces
    # this regardless of the graph's own requires_approval value).
    status = asyncio.run(orch.run())
    assert status == RunStatus.PAUSED_FOR_APPROVAL
    assert orch.node_states["design-schema"].state == NodeState.NEEDS_APPROVAL
    assert orch.node_states["req-review"].state == NodeState.PASSED

    orch.approve("design-schema", approved=True, approver="alice", reason="schema reviewed")
    status = asyncio.run(orch.run())

    # Second pause: the release gate itself.
    assert status == RunStatus.PAUSED_FOR_APPROVAL
    assert orch.node_states["release-gate"].state == NodeState.NEEDS_APPROVAL
    for node_id in (
        "req-review", "design-schema", "design-api-contract", "implement-storage",
        "implement-create-api", "implement-redirect-api", "implement-analytics-api",
        "unit-tests", "integration-tests", "write-docs",
    ):
        assert orch.node_states[node_id].state == NodeState.PASSED, node_id

    orch.approve("release-gate", approved=True, approver="alice", reason="all green")
    status = asyncio.run(orch.run())

    assert status == RunStatus.COMPLETED
    assert orch.node_states["release-gate"].state == NodeState.PASSED

    metrics = compute_metrics(store.read_events())
    assert metrics["success_rate"] == 1.0

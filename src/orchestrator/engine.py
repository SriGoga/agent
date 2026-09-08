"""The orchestration engine: walks a GraphSpec as a stateful, non-linear DAG executor.

Supports (per the assignment's orchestration requirements):
- sequential + parallel paths with synchronization (readiness is computed from the graph,
  independent nodes naturally execute concurrently via asyncio.gather)
- cross-stage context/lineage preservation (the `artifacts` dict + JSONL event log)
- human-approval checkpoints that pause the whole run until resumed
- bounded retry with backoff, rollback on exhaustion, and a safe-stop circuit breaker
- policy guardrails (entry gates before a node runs, exit gates on its output)
- dynamic re-planning: marking a node dirty invalidates it and everything downstream
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from orchestrator.models import (
    GraphSpec,
    LineageEvent,
    NodeRuntime,
    NodeState,
    RunStatus,
)
from orchestrator.policy import ENTRY_POLICIES, EXIT_POLICIES, PolicyContext, PolicyFn, PolicyViolation
from orchestrator.registry import ActionRegistry, StepContext
from orchestrator.store import LineageStore

_TERMINAL = {NodeState.PASSED, NodeState.FAILED, NodeState.ROLLED_BACK, NodeState.SKIPPED}
_UNSUCCESSFUL_TERMINAL = {NodeState.FAILED, NodeState.ROLLED_BACK, NodeState.SKIPPED}


class Orchestrator:
    def __init__(
        self,
        graph: GraphSpec,
        registry: ActionRegistry,
        store: LineageStore,
        run_id: str | None = None,
        entry_policies: list[PolicyFn] | None = None,
        exit_policies: list[PolicyFn] | None = None,
        safe_stop_threshold: int = 3,
    ) -> None:
        self.graph = graph
        self.registry = registry
        self.store = store
        self.run_id = run_id or store.run_id
        self.entry_policies = entry_policies if entry_policies is not None else ENTRY_POLICIES
        self.exit_policies = exit_policies if exit_policies is not None else EXIT_POLICIES
        self.safe_stop_threshold = safe_stop_threshold
        self.node_states: dict[str, NodeRuntime] = {n.id: NodeRuntime() for n in graph.nodes}
        self.artifacts: dict[str, dict] = {}
        self.status = RunStatus.RUNNING
        self.failure_count = 0

    # -- persistence -----------------------------------------------------
    def _log(self, node_id: str, event: str, attempt: int = 0, detail: str = "", duration: float | None = None) -> None:
        self.store.append_event(
            LineageEvent(
                ts=time.time(),
                run_id=self.run_id,
                node_id=node_id,
                event=event,
                attempt=attempt,
                detail=detail,
                duration_seconds=duration,
            )
        )

    def _persist(self) -> None:
        state = {
            "run_id": self.run_id,
            "graph_name": self.graph.name,
            "status": self.status.value,
            "failure_count": self.failure_count,
            "artifacts": self.artifacts,
            "nodes": {
                nid: {
                    "state": rt.state.value,
                    "attempts": rt.attempts,
                    "output": rt.output,
                    "error": rt.error,
                    "approval_decision": rt.approval_decision,
                    "approver": rt.approver,
                    "approval_reason": rt.approval_reason,
                }
                for nid, rt in self.node_states.items()
            },
        }
        self.store.save_state(state)

    @classmethod
    def load(
        cls,
        graph: GraphSpec,
        registry: ActionRegistry,
        store: LineageStore,
        **kwargs,
    ) -> "Orchestrator":
        state = store.load_state()
        orch = cls(graph, registry, store, run_id=store.run_id, **kwargs)
        if state is None:
            return orch
        orch.status = RunStatus(state["status"])
        orch.failure_count = state.get("failure_count", 0)
        orch.artifacts = state.get("artifacts", {})
        for nid, node_state in state.get("nodes", {}).items():
            rt = orch.node_states[nid]
            rt.state = NodeState(node_state["state"])
            rt.attempts = node_state["attempts"]
            rt.output = node_state["output"]
            rt.error = node_state["error"]
            rt.approval_decision = node_state["approval_decision"]
            rt.approver = node_state["approver"]
            rt.approval_reason = node_state["approval_reason"]
        return orch

    # -- graph traversal ---------------------------------------------------
    def _ready_nodes(self):
        ready = []
        for n in self.graph.nodes:
            rt = self.node_states[n.id]
            if rt.state != NodeState.PENDING:
                continue
            if all(self.node_states[dep].state == NodeState.PASSED for dep in n.depends_on):
                ready.append(n)
        return ready

    def _propagate_failure(self, node_id: str) -> None:
        for dependent_id in self.graph.transitive_dependents(node_id):
            rt = self.node_states[dependent_id]
            if rt.state in _TERMINAL:
                continue
            rt.state = NodeState.SKIPPED
            self._log(dependent_id, "skipped", detail=f"upstream node '{node_id}' did not pass")

    # -- execution -----------------------------------------------------
    async def _execute_node(self, node) -> None:
        rt = self.node_states[node.id]

        entry_ctx = PolicyContext(node=node, graph=self.graph, node_states=self.node_states, output=None)
        try:
            for policy in self.entry_policies:
                policy(entry_ctx)
        except PolicyViolation as exc:
            rt.state = NodeState.FAILED
            rt.error = str(exc)
            self._log(node.id, "policy_blocked", detail=str(exc))
            self._propagate_failure(node.id)
            return

        if node.requires_approval and rt.approval_decision is None:
            rt.state = NodeState.NEEDS_APPROVAL
            self._log(node.id, "needs_approval", detail=node.description)
            return
        if node.requires_approval and rt.approval_decision == "rejected":
            rt.state = NodeState.ROLLED_BACK
            self._log(node.id, "rejected", detail=rt.approval_reason or "")
            self._propagate_failure(node.id)
            return

        rt.state = NodeState.RUNNING
        self._log(node.id, "started")
        step = self.registry.get_action(node.action)

        attempt = 0
        last_err = ""
        start = time.time()
        max_attempts = max(node.retry.max_attempts, 1)
        while attempt < max_attempts:
            attempt += 1
            rt.attempts = attempt
            try:
                output = await step(StepContext(node_id=node.id, artifacts=self.artifacts, attempt=attempt))
                exit_ctx = PolicyContext(node=node, graph=self.graph, node_states=self.node_states, output=output)
                for policy in self.exit_policies:
                    policy(exit_ctx)
                rt.output = output
                rt.state = NodeState.PASSED
                self.artifacts[node.id] = output
                self._log(node.id, "passed", attempt=attempt, duration=time.time() - start)
                return
            except PolicyViolation as exc:
                last_err = str(exc)
                self._log(node.id, "policy_blocked", attempt=attempt, detail=last_err)
                break
            except Exception as exc:  # noqa: BLE001 - a failing step is expected control flow here
                last_err = str(exc)
                self._log(node.id, "failed_attempt", attempt=attempt, detail=last_err)
                if attempt < max_attempts:
                    self._log(node.id, "retrying", attempt=attempt)
                    if node.retry.backoff_seconds:
                        await asyncio.sleep(node.retry.backoff_seconds)

        rt.state = NodeState.FAILED
        rt.error = last_err
        self._log(node.id, "failed", attempt=attempt, detail=last_err, duration=time.time() - start)

        if node.rollback_action:
            rollback = self.registry.get_rollback(node.rollback_action)
            if rollback is not None:
                try:
                    await rollback(StepContext(node_id=node.id, artifacts=self.artifacts, attempt=attempt))
                    rt.state = NodeState.ROLLED_BACK
                    self._log(node.id, "rolled_back", detail=node.rollback_action)
                except Exception as exc:  # noqa: BLE001
                    self._log(node.id, "rollback_failed", detail=str(exc))

        self.failure_count += 1
        if self.failure_count >= self.safe_stop_threshold:
            self.status = RunStatus.SAFE_STOPPED
            self._log("__run__", "safe_stopped", detail=f"failure threshold {self.safe_stop_threshold} reached")

        self._propagate_failure(node.id)

    async def run(self) -> RunStatus:
        if self.status not in (RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL):
            return self.status
        self.status = RunStatus.RUNNING

        while True:
            pending_approval = [
                n for n in self.graph.nodes if self.node_states[n.id].state == NodeState.NEEDS_APPROVAL
            ]
            if pending_approval:
                self.status = RunStatus.PAUSED_FOR_APPROVAL
                self._persist()
                return self.status

            ready = self._ready_nodes()
            if not ready:
                break

            await asyncio.gather(*(self._execute_node(n) for n in ready))
            self._persist()

            if self.status == RunStatus.SAFE_STOPPED:
                return self.status

        if all(self.node_states[n.id].state in _TERMINAL for n in self.graph.nodes):
            unsuccessful = any(self.node_states[n.id].state in _UNSUCCESSFUL_TERMINAL for n in self.graph.nodes)
            self.status = RunStatus.FAILED if unsuccessful else RunStatus.COMPLETED
        self._persist()
        return self.status

    # -- human-in-the-loop control -----------------------------------------
    def approve(self, node_id: str, approved: bool, approver: str, reason: str = "") -> None:
        rt = self.node_states[node_id]
        if rt.state != NodeState.NEEDS_APPROVAL:
            raise ValueError(f"node '{node_id}' is not waiting for approval (state={rt.state.value})")
        rt.approval_decision = "approved" if approved else "rejected"
        rt.approver = approver
        rt.approval_reason = reason
        rt.state = NodeState.PENDING
        self._log(node_id, "approved" if approved else "rejected", detail=f"by {approver}: {reason}")
        self._persist()

    # -- dynamic re-planning ------------------------------------------------
    def replan(self, node_id: str, reason: str = "") -> None:
        """Invalidate a node and everything transitively downstream of it, so the next
        run() call re-executes them -- used when an upstream output changes."""
        dirty = {node_id} | self.graph.transitive_dependents(node_id)
        for nid in dirty:
            self.node_states[nid] = NodeRuntime()
            self._log(nid, "replanned", detail=reason)
        if self.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.SAFE_STOPPED):
            self.status = RunStatus.RUNNING
        self.failure_count = 0
        self._persist()


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]

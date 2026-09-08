"""Data model for the orchestration graph, run state, and lineage events."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    PASSED = "passed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SAFE_STOPPED = "safe_stopped"


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0


@dataclass
class NodeSpec:
    id: str
    stage: str
    description: str
    depends_on: list[str]
    action: str
    requires_approval: bool = False
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    rollback_action: str | None = None


@dataclass
class GraphSpec:
    name: str
    description: str
    nodes: list[NodeSpec]

    def node(self, node_id: str) -> NodeSpec:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"unknown node id: {node_id}")

    def dependents_of(self, node_id: str) -> list[str]:
        """Direct children: nodes that declare node_id in depends_on."""
        return [n.id for n in self.nodes if node_id in n.depends_on]

    def transitive_dependents(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for child in self.dependents_of(current):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return seen

    @staticmethod
    def from_dict(data: dict) -> "GraphSpec":
        nodes = []
        for n in data["nodes"]:
            retry = RetryPolicy(**n.get("retry", {}))
            nodes.append(
                NodeSpec(
                    id=n["id"],
                    stage=n["stage"],
                    description=n.get("description", ""),
                    depends_on=list(n.get("depends_on", [])),
                    action=n["action"],
                    requires_approval=bool(n.get("requires_approval", False)),
                    retry=retry,
                    rollback_action=n.get("rollback_action"),
                )
            )
        return GraphSpec(name=data["name"], description=data.get("description", ""), nodes=nodes)


@dataclass
class NodeRuntime:
    state: NodeState = NodeState.PENDING
    attempts: int = 0
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    approval_decision: str | None = None  # "approved" | "rejected"
    approver: str | None = None
    approval_reason: str | None = None


@dataclass
class LineageEvent:
    """One audit-grade record: what happened, to which node, why, and when."""

    ts: float
    run_id: str
    node_id: str
    event: str  # e.g. "started", "passed", "failed", "retrying", "rolled_back",
    #             "needs_approval", "approved", "rejected", "skipped",
    #             "policy_blocked", "replanned", "safe_stopped"
    attempt: int = 0
    detail: str = ""
    duration_seconds: float | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "event": self.event,
            "attempt": self.attempt,
            "detail": self.detail,
            "duration_seconds": self.duration_seconds,
        }

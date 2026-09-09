"""Policy guardrails: security, compliance, and change-control checks applied around node
execution, independent of what any individual node/graph author declared. This is the
governance layer -- a node can't opt itself out of a guardrail by omitting a flag."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from orchestrator.models import GraphSpec, NodeRuntime, NodeSpec, NodeState


class PolicyViolation(Exception):
    def __init__(self, policy_name: str, reason: str):
        self.policy_name = policy_name
        self.reason = reason
        super().__init__(f"{policy_name}: {reason}")


@dataclass
class PolicyContext:
    node: NodeSpec
    graph: GraphSpec
    node_states: dict[str, NodeRuntime]
    output: dict[str, Any] | None = None


PolicyFn = Callable[[PolicyContext], None]


def require_tests_before_release(ctx: PolicyContext) -> None:
    """Compliance: nothing reaches a 'release' stage node unless every 'testing' stage
    node in the graph has already passed."""
    if ctx.node.stage != "release":
        return
    for n in ctx.graph.nodes:
        if n.stage != "testing":
            continue
        rt = ctx.node_states.get(n.id)
        if rt is None or rt.state != NodeState.PASSED:
            raise PolicyViolation(
                "require_tests_before_release",
                f"testing node '{n.id}' has not passed (state="
                f"{rt.state.value if rt else 'unknown'})",
            )


def require_approval_on_schema_changes(ctx: PolicyContext) -> None:
    """Change control: any node whose id/action touches the data schema must require
    human approval, regardless of how the graph JSON was authored."""
    touches_schema = "schema" in ctx.node.id or "schema" in ctx.node.action
    if touches_schema and not ctx.node.requires_approval:
        raise PolicyViolation(
            "require_approval_on_schema_changes",
            f"node '{ctx.node.id}' changes the schema but is not marked requires_approval",
        )


_SECRET_PATTERNS = [
    re.compile(r"(?i)password\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def no_cross_owner_data_exposure(ctx: PolicyContext) -> None:
    """Change control / privacy: blocks a node's output if it bundles items belonging to
    more than one distinct owner_id -- e.g. an aggregate/leaderboard-style endpoint that
    should be scoped to a single caller but was implemented (or later modified) to mix
    owners together. See docs/ambiguous-analysis.md (ambiguity B5)."""
    if not ctx.output:
        return
    items = ctx.output.get("items")
    if not isinstance(items, list):
        return
    owner_ids = {item.get("owner_id") for item in items if isinstance(item, dict) and "owner_id" in item}
    if len(owner_ids) > 1:
        raise PolicyViolation(
            "no_cross_owner_data_exposure",
            f"node '{ctx.node.id}' output mixes {len(owner_ids)} distinct owner_ids in one response",
        )


def no_plaintext_secrets_in_output(ctx: PolicyContext) -> None:
    """Security: scan a node's produced output for obvious hardcoded secrets before
    accepting it as passed."""
    if not ctx.output:
        return
    for value in ctx.output.values():
        if not isinstance(value, str):
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                raise PolicyViolation(
                    "no_plaintext_secrets_in_output",
                    f"node '{ctx.node.id}' output matched a hardcoded-secret pattern",
                )


ENTRY_POLICIES: list[PolicyFn] = [
    require_tests_before_release,
    require_approval_on_schema_changes,
]

EXIT_POLICIES: list[PolicyFn] = [
    no_plaintext_secrets_in_output,
    no_cross_owner_data_exposure,
]

"""Step implementations for src/scenarios/ambiguous.json (Phase 6).

Same verify-and-gate stance as the other scenario step modules. The one thing worth calling
out: spike_scope_decision actually exercises the real orchestrator.policy function against a
deliberately-wrong (mixed-owner) output, rather than just asserting a design decision in
prose -- see docs/ambiguous-analysis.md, ambiguity B5.
"""
from __future__ import annotations

import inspect
import tempfile

from orchestrator.models import NodeSpec, RetryPolicy
from orchestrator.policy import PolicyContext, PolicyViolation, no_cross_owner_data_exposure
from orchestrator.registry import ActionRegistry, StepContext
from scenarios._common import REPO_ROOT, run_pytest

_REQUIRED_AMBIGUITY_MARKERS = ["B1", "B2", "B3", "B4", "B5"]


async def clarify_requirements(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "ambiguous-analysis.md"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [m for m in _REQUIRED_AMBIGUITY_MARKERS if m not in content]
    if missing:
        raise RuntimeError(f"docs/ambiguous-analysis.md missing ambiguity markers: {missing}")
    return {"ambiguities_resolved": _REQUIRED_AMBIGUITY_MARKERS}


async def spike_scope_decision(ctx: StepContext) -> dict:
    """Proves the rejected alternative (a global leaderboard mixing every owner's links) is
    actually blocked by the real no_cross_owner_data_exposure policy, not just avoided by
    convention."""
    dummy_node = NodeSpec(id="spike", stage="design", description="", depends_on=[], action="x", retry=RetryPolicy())
    mixed_output = {"items": [{"owner_id": "alice", "code": "a"}, {"owner_id": "bob", "code": "b"}]}
    policy_ctx = PolicyContext(node=dummy_node, graph=None, node_states={}, output=mixed_output)
    try:
        no_cross_owner_data_exposure(policy_ctx)
    except PolicyViolation:
        pass  # expected: the risky global-leaderboard shape is correctly rejected
    else:
        raise RuntimeError(
            "no_cross_owner_data_exposure failed to block a mixed-owner output -- guardrail regression"
        )
    return {"decision": "scoped-to-owner_id", "rejected_alternative": "global leaderboard across all owners"}


async def design_scoped_endpoint(ctx: StepContext) -> dict:
    from url_shortener import main as main_module

    sig = inspect.signature(main_module.top_links)
    if "owner_id" not in sig.parameters:
        raise RuntimeError("top_links endpoint does not require owner_id")
    return {"endpoint": "GET /links/top", "scoped_param": "owner_id"}


async def implement_top_links(ctx: StepContext) -> dict:
    from url_shortener.privacy import hash_ip
    from url_shortener.storage import LinkRepository

    with tempfile.TemporaryDirectory() as tmp:
        repo = LinkRepository(f"{tmp}/t.db")
        repo.create_link("alices", "https://example.com/a", "alice")
        repo.create_link("bobs", "https://example.com/b", "bob")
        repo.record_click("bobs", None, None, hash_ip("9.9.9.9"))
        results = repo.top_links("alice", "clicks", None, 10)

    codes = {r["code"] for r in results}
    if "bobs" in codes:
        raise RuntimeError("top_links leaked another owner's link")
    return {"scoped_check": "ok"}


async def run_tests(ctx: StepContext) -> dict:
    summary = await run_pytest("tests/test_top_links.py")
    return {"tests": summary}


async def write_docs(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "api.md"
    if "links/top" not in path.read_text(encoding="utf-8"):
        raise RuntimeError("docs/api.md does not document GET /links/top")
    return {"docs_updated": True}


async def release_readiness_check(ctx: StepContext) -> dict:
    return {"ready": True, "feature": "top-links (owner-scoped)"}


async def _log_only_rollback(ctx: StepContext) -> dict:
    return {"rollback_logged_for": ctx.node_id}


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register_action("clarify_requirements", clarify_requirements)
    reg.register_action("spike_scope_decision", spike_scope_decision)
    reg.register_action("design_scoped_endpoint", design_scoped_endpoint)
    reg.register_action("implement_top_links", implement_top_links)
    reg.register_action("run_tests", run_tests)
    reg.register_action("write_docs", write_docs)
    reg.register_action("release_readiness_check", release_readiness_check)
    reg.register_rollback("revert_top_links", _log_only_rollback)
    reg.register_rollback("rollback_release", _log_only_rollback)
    return reg

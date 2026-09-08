"""Step implementations for src/scenarios/demo.json -- a self-contained happy-path
walkthrough of the engine (parallel branches, a retrying node, a human-approval gate),
independent of the real URL Shortener scenarios so the engine can be exercised on its own."""
from __future__ import annotations

import asyncio

from orchestrator.registry import ActionRegistry, StepContext


async def demo_collect_input(ctx: StepContext) -> dict:
    await asyncio.sleep(0)
    return {"note": "input collected"}


async def demo_flaky_build(ctx: StepContext) -> dict:
    """Fails on the first attempt, succeeds on retry -- demonstrates bounded retry."""
    await asyncio.sleep(0)
    if ctx.attempt < 2:
        raise RuntimeError("simulated transient build failure")
    return {"note": "build succeeded on retry", "attempt": ctx.attempt}


async def demo_noop(ctx: StepContext) -> dict:
    await asyncio.sleep(0)
    return {"note": f"{ctx.node_id} ok"}


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register_action("demo_collect_input", demo_collect_input)
    reg.register_action("demo_flaky_build", demo_flaky_build)
    reg.register_action("demo_noop", demo_noop)
    return reg

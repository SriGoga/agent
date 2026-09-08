"""Registry mapping action/rollback names (from graph JSON) to Python callables.

Keeping this indirection means the graph data (src/scenarios/*.json) never embeds code —
only identifiers — and different scenarios can share or override step implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

StepFn = Callable[["StepContext"], Awaitable[dict]]


@dataclass
class StepContext:
    """What a step function receives: its own node id, accumulated cross-node artifacts,
    and the current attempt number (1-indexed) so a flaky/simulated step can behave
    differently on retry."""

    node_id: str
    artifacts: dict[str, Any]
    attempt: int


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, StepFn] = {}
        self._rollbacks: dict[str, StepFn] = {}

    def action(self, name: str):
        def deco(fn: StepFn) -> StepFn:
            self._actions[name] = fn
            return fn

        return deco

    def rollback(self, name: str):
        def deco(fn: StepFn) -> StepFn:
            self._rollbacks[name] = fn
            return fn

        return deco

    def register_action(self, name: str, fn: StepFn) -> None:
        self._actions[name] = fn

    def register_rollback(self, name: str, fn: StepFn) -> None:
        self._rollbacks[name] = fn

    def get_action(self, name: str) -> StepFn:
        if name not in self._actions:
            raise KeyError(f"no action registered for '{name}'")
        return self._actions[name]

    def get_rollback(self, name: str) -> StepFn | None:
        return self._rollbacks.get(name)

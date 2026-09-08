"""Persists run state and the append-only lineage log so a run can be paused for approval,
resumed, re-planned, or audited after the fact -- across separate process invocations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.models import LineageEvent

DEFAULT_RUNS_ROOT = Path(".orchestrator/runs")


class LineageStore:
    def __init__(self, run_id: str, root: Path | None = None):
        self.run_id = run_id
        self.root = (root or DEFAULT_RUNS_ROOT) / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"
        self.state_path = self.root / "state.json"

    def append_event(self, event: LineageEvent) -> None:
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def read_events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        with self.events_path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def existing_run_ids(root: Path | None = None) -> list[str]:
        base = root or DEFAULT_RUNS_ROOT
        if not base.exists():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())

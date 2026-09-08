"""Command-line control surface for the orchestrator: run, inspect status, approve/reject
a paused gate, re-plan from a changed node, and report reliability metrics.

Usage (after `pip install -e ".[dev]"` from the repo root):
    python -m orchestrator.cli run --graph src/scenarios/demo.json
    python -m orchestrator.cli status --run-id <id>
    python -m orchestrator.cli approve --run-id <id> --node approval-gate --approver alice
    python -m orchestrator.cli replan --run-id <id> --node flaky-build --reason "spec changed"
    python -m orchestrator.cli report --run-id <id>
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

from orchestrator.engine import Orchestrator, new_run_id
from orchestrator.metrics import compute_metrics
from orchestrator.models import GraphSpec
from orchestrator.store import DEFAULT_RUNS_ROOT, LineageStore

# Maps a graph's "name" field to the module exposing build_registry() for its actions.
STEP_MODULES = {
    "demo": "scenarios.demo_steps",
    "greenfield-url-shortener": "scenarios.greenfield_steps",
    "brownfield-expiry-cleanup": "scenarios.brownfield_steps",
    "ambiguous-analytics-dashboard": "scenarios.ambiguous_steps",
}


def _load_graph(graph_path: Path) -> GraphSpec:
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    return GraphSpec.from_dict(data)


def _registry_for(graph: GraphSpec):
    module_name = STEP_MODULES.get(graph.name)
    if module_name is None:
        raise SystemExit(f"no step module registered for graph '{graph.name}'")
    module = importlib.import_module(module_name)
    return module.build_registry()


def _meta_path(run_id: str) -> Path:
    return DEFAULT_RUNS_ROOT / run_id / "meta.json"


def _write_meta(run_id: str, graph_path: Path) -> None:
    path = _meta_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"graph_path": str(graph_path)}), encoding="utf-8")


def _read_meta(run_id: str) -> dict:
    path = _meta_path(run_id)
    if not path.exists():
        raise SystemExit(f"no meta found for run '{run_id}' (unknown run id?)")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_run(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph)
    graph = _load_graph(graph_path)
    registry = _registry_for(graph)
    run_id = args.run_id or new_run_id()
    store = LineageStore(run_id)
    _write_meta(run_id, graph_path)
    orch = Orchestrator.load(graph, registry, store)
    status = asyncio.run(orch.run())
    print(f"run_id={run_id} status={status.value}")
    _print_node_states(orch)


def cmd_status(args: argparse.Namespace) -> None:
    store = LineageStore(args.run_id)
    state = store.load_state()
    if state is None:
        raise SystemExit(f"no state found for run '{args.run_id}'")
    print(json.dumps(state, indent=2))


def cmd_approve(args: argparse.Namespace) -> None:
    meta = _read_meta(args.run_id)
    graph = _load_graph(Path(meta["graph_path"]))
    registry = _registry_for(graph)
    store = LineageStore(args.run_id)
    orch = Orchestrator.load(graph, registry, store)
    orch.approve(args.node, approved=not args.reject, approver=args.approver, reason=args.reason or "")
    status = asyncio.run(orch.run())
    print(f"run_id={args.run_id} status={status.value}")
    _print_node_states(orch)


def cmd_replan(args: argparse.Namespace) -> None:
    meta = _read_meta(args.run_id)
    graph = _load_graph(Path(meta["graph_path"]))
    registry = _registry_for(graph)
    store = LineageStore(args.run_id)
    orch = Orchestrator.load(graph, registry, store)
    orch.replan(args.node, reason=args.reason or "")
    status = asyncio.run(orch.run())
    print(f"run_id={args.run_id} status={status.value}")
    _print_node_states(orch)


def cmd_report(args: argparse.Namespace) -> None:
    store = LineageStore(args.run_id)
    events = store.read_events()
    metrics = compute_metrics(events)
    print(json.dumps(metrics, indent=2))


def _print_node_states(orch: Orchestrator) -> None:
    for n in orch.graph.nodes:
        rt = orch.node_states[n.id]
        print(f"  {n.id:<20} {rt.state.value:<16} attempts={rt.attempts}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Start (or resume) a graph run")
    p_run.add_argument("--graph", required=True, help="Path to a scenario graph JSON file")
    p_run.add_argument("--run-id", default=None, help="Resume an existing run id instead of starting a new one")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Print a run's persisted state")
    p_status.add_argument("--run-id", required=True)
    p_status.set_defaults(func=cmd_status)

    p_approve = sub.add_parser("approve", help="Approve or reject a node paused for approval")
    p_approve.add_argument("--run-id", required=True)
    p_approve.add_argument("--node", required=True)
    p_approve.add_argument("--reject", action="store_true")
    p_approve.add_argument("--approver", required=True)
    p_approve.add_argument("--reason", default="")
    p_approve.set_defaults(func=cmd_approve)

    p_replan = sub.add_parser("replan", help="Invalidate a node and its downstream nodes, then resume")
    p_replan.add_argument("--run-id", required=True)
    p_replan.add_argument("--node", required=True)
    p_replan.add_argument("--reason", default="")
    p_replan.set_defaults(func=cmd_replan)

    p_report = sub.add_parser("report", help="Print reliability metrics for a run")
    p_report.add_argument("--run-id", required=True)
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()

"""Reliability metrics derived from a run's lineage events: success rate, retry/rollback
frequency, MTTR, and end-to-end latency."""
from __future__ import annotations

from typing import Any


def compute_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "total_nodes": 0,
            "passed_nodes": 0,
            "success_rate": 0.0,
            "retry_count": 0,
            "rollback_count": 0,
            "safe_stop_count": 0,
            "mttr_seconds": 0.0,
            "end_to_end_latency_seconds": 0.0,
        }

    node_events = [e for e in events if e["node_id"] != "__run__"]
    started = min(e["ts"] for e in events)
    ended = max(e["ts"] for e in events)

    total_nodes = len({e["node_id"] for e in node_events})
    passed_nodes = len({e["node_id"] for e in node_events if e["event"] == "passed"})
    retry_count = sum(1 for e in node_events if e["event"] == "retrying")
    rollback_count = sum(1 for e in node_events if e["event"] == "rolled_back")
    safe_stop_count = sum(1 for e in events if e["event"] == "safe_stopped")

    by_node: dict[str, list[dict]] = {}
    for e in node_events:
        by_node.setdefault(e["node_id"], []).append(e)

    mttrs: list[float] = []
    for evs in by_node.values():
        evs_sorted = sorted(evs, key=lambda e: e["ts"])
        first_failure_ts = next((e["ts"] for e in evs_sorted if e["event"] == "failed_attempt"), None)
        passed_ts = next((e["ts"] for e in evs_sorted if e["event"] == "passed"), None)
        if first_failure_ts is not None and passed_ts is not None and passed_ts >= first_failure_ts:
            mttrs.append(passed_ts - first_failure_ts)

    return {
        "total_nodes": total_nodes,
        "passed_nodes": passed_nodes,
        "success_rate": round(passed_nodes / total_nodes, 4) if total_nodes else 0.0,
        "retry_count": retry_count,
        "rollback_count": rollback_count,
        "safe_stop_count": safe_stop_count,
        "mttr_seconds": round(sum(mttrs) / len(mttrs), 4) if mttrs else 0.0,
        "end_to_end_latency_seconds": round(ended - started, 4),
    }

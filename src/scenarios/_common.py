"""Shared helpers for scenario step modules."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


async def run_pytest(*test_paths: str) -> str:
    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "pytest", *test_paths, "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    result = await asyncio.to_thread(_run)
    if result.returncode != 0:
        raise RuntimeError(f"pytest failed for {test_paths}:\n{result.stdout[-2000:]}\n{result.stderr[-1000:]}")
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "ok"

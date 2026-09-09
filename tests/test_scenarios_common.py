"""docs/risks.md: 'unbounded test execution time' -- a bounded-retry node is meaningless if
a single attempt can hang forever."""
from __future__ import annotations

import asyncio

import pytest

from scenarios._common import run_pytest


def test_run_pytest_raises_on_timeout():
    async def _go():
        with pytest.raises(RuntimeError, match="timed out"):
            # An unreasonably short timeout: even pytest collection alone takes longer than 1ms.
            await run_pytest("tests/test_url_shortener.py", timeout=0.001)

    asyncio.run(_go())


def test_run_pytest_succeeds_within_a_reasonable_timeout():
    async def _go():
        summary = await run_pytest("tests/test_codegen.py", timeout=30)
        assert "passed" in summary

    asyncio.run(_go())

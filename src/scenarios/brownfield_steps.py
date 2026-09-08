"""Step implementations for src/scenarios/brownfield.json (Phase 5).

Same design stance as greenfield_steps.py: these steps verify the already-written brownfield
change against real code -- including, critically, verifying the migration against a
hand-built pre-existing database, since that is the actual brownfield risk here.
"""
from __future__ import annotations

import inspect
import sqlite3
import tempfile
import time

from orchestrator.registry import ActionRegistry, StepContext
from scenarios._common import REPO_ROOT, run_pytest

_OLD_SCHEMA = """
CREATE TABLE links (
    code TEXT PRIMARY KEY, target_url TEXT NOT NULL, owner_id TEXT NOT NULL,
    created_at REAL NOT NULL, expires_at REAL, deleted_at REAL
);
CREATE TABLE clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, ts REAL NOT NULL,
    referrer TEXT, user_agent TEXT
);
"""


async def review_impacted_modules(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "brownfield-analysis.md"
    if not path.exists():
        raise RuntimeError("docs/brownfield-analysis.md is missing")
    return {"analysis_doc": str(path.relative_to(REPO_ROOT))}


async def design_schema_change(ctx: StepContext) -> dict:
    from url_shortener.storage import LinkRepository

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(_OLD_SCHEMA)
        conn.commit()
        conn.close()

        LinkRepository(db_path)  # constructing it must run the migration

        check_conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in check_conn.execute("PRAGMA table_info(clicks)").fetchall()}
        finally:
            check_conn.close()
    if "ip_hash" not in cols:
        raise RuntimeError("migration did not add ip_hash to a pre-existing clicks table")
    return {"migration_shape": "verified"}


async def implement_storage_migration(ctx: StepContext) -> dict:
    from url_shortener.storage import LinkRepository

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/legacy2.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(_OLD_SCHEMA)
        conn.execute(
            "INSERT INTO links VALUES ('legacy', 'https://example.com', 'owner', ?, NULL, NULL)",
            (time.time(),),
        )
        conn.commit()
        conn.close()

        repo = LinkRepository(db_path)
        if repo.get_link("legacy") is None:
            raise RuntimeError("migration lost a pre-existing row")
    return {"data_preserved": True}


async def implement_analytics_update(ctx: StepContext) -> dict:
    from url_shortener.privacy import hash_ip
    from url_shortener.storage import LinkRepository

    with tempfile.TemporaryDirectory() as tmp:
        repo = LinkRepository(f"{tmp}/a.db")
        repo.create_link("code1", "https://example.com", "owner")
        repo.record_click("code1", None, None, hash_ip("1.1.1.1"))
        repo.record_click("code1", None, None, hash_ip("1.1.1.1"))
        repo.record_click("code1", None, None, hash_ip("2.2.2.2"))
        data = repo.analytics("code1")

    if data.get("unique_visitors") != 2:
        raise RuntimeError(f"expected unique_visitors=2, got {data.get('unique_visitors')}")
    return {"unique_visitors_check": "ok", "fields": sorted(data.keys())}


async def implement_redirect_update(ctx: StepContext) -> dict:
    from url_shortener import main as main_module

    source = inspect.getsource(main_module.redirect)
    if "hash_ip" not in source:
        raise RuntimeError("redirect handler does not hash the client IP before recording a click")
    return {"redirect_update": "verified"}


async def run_regression_tests(ctx: StepContext) -> dict:
    summary = await run_pytest(
        "tests/test_brownfield_unique_visitors.py",
        "tests/test_privacy.py",
        "tests/test_url_shortener.py",
    )
    return {"regression_tests": summary}


async def write_docs_update(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "api.md"
    if "unique_visitors" not in path.read_text(encoding="utf-8"):
        raise RuntimeError("docs/api.md does not document unique_visitors")
    return {"docs_updated": True}


async def release_readiness_check(ctx: StepContext) -> dict:
    return {"ready": True, "change": "unique-visitor analytics"}


async def _log_only_rollback(ctx: StepContext) -> dict:
    """Source-code changes are rolled back with `git revert`, not at runtime -- this just
    records that a rollback was triggered, for the lineage log."""
    return {"rollback_logged_for": ctx.node_id}


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register_action("review_impacted_modules", review_impacted_modules)
    reg.register_action("design_schema_change", design_schema_change)
    reg.register_action("implement_storage_migration", implement_storage_migration)
    reg.register_action("implement_analytics_update", implement_analytics_update)
    reg.register_action("implement_redirect_update", implement_redirect_update)
    reg.register_action("run_regression_tests", run_regression_tests)
    reg.register_action("write_docs_update", write_docs_update)
    reg.register_action("release_readiness_check", release_readiness_check)
    reg.register_rollback("revert_storage_migration", _log_only_rollback)
    reg.register_rollback("revert_analytics_update", _log_only_rollback)
    reg.register_rollback("revert_redirect_update", _log_only_rollback)
    reg.register_rollback("rollback_release", _log_only_rollback)
    return reg

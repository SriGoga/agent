"""Step implementations for src/scenarios/greenfield.json.

Design choice worth being explicit about: these steps do not generate code from nothing --
the URL Shortener source already exists (this phase's deliverable). Each node here performs
the same job a real CI/CD pipeline performs against an already-written codebase: verify the
design decisions hold, the implementation imports and behaves correctly, the real test suite
passes, and the docs exist -- then gate release readiness on all of that. That is a realistic
and defensible shape for an SDLC orchestrator: it verifies and gates, it does not author.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from orchestrator.registry import ActionRegistry, StepContext

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _run_pytest(*test_paths: str) -> str:
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


async def reuse_requirements_doc(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "requirements.md"
    if not path.exists():
        raise RuntimeError("docs/requirements.md is missing")
    return {"requirements_doc": str(path.relative_to(REPO_ROOT))}


async def design_data_schema(ctx: StepContext) -> dict:
    from url_shortener.storage import SCHEMA

    required_tables = ["links", "clicks", "idempotency_keys"]
    missing = [t for t in required_tables if f"TABLE IF NOT EXISTS {t}" not in SCHEMA]
    if missing:
        raise RuntimeError(f"schema design missing expected tables: {missing}")
    return {"tables": required_tables}


async def design_api_contract(ctx: StepContext) -> dict:
    from url_shortener.main import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    required = {"/links", "/links/{code}/analytics", "/links/{code}", "/{code}"}
    missing = required - paths
    if missing:
        raise RuntimeError(f"API contract missing expected paths: {missing}")
    return {"paths": sorted(required)}


async def implement_storage_layer(ctx: StepContext) -> dict:
    import tempfile

    from url_shortener.storage import LinkRepository

    with tempfile.TemporaryDirectory() as tmp:
        repo = LinkRepository(f"{tmp}/verify.db")
        repo.create_link("verifycode", "https://example.com", "verify-owner")
        if repo.get_link("verifycode") is None:
            raise RuntimeError("storage layer failed a create+get round trip")
    return {"storage": "verified"}


async def implement_create_endpoint(ctx: StepContext) -> dict:
    from url_shortener.main import app

    if not any(getattr(r, "path", None) == "/links" and "POST" in getattr(r, "methods", set()) for r in app.routes):
        raise RuntimeError("POST /links route not found")
    return {"endpoint": "POST /links"}


async def implement_redirect_endpoint(ctx: StepContext) -> dict:
    from url_shortener.main import app

    if not any(getattr(r, "path", None) == "/{code}" and "GET" in getattr(r, "methods", set()) for r in app.routes):
        raise RuntimeError("GET /{code} route not found")
    return {"endpoint": "GET /{code}"}


async def implement_analytics_endpoint(ctx: StepContext) -> dict:
    from url_shortener.main import app

    target = "/links/{code}/analytics"
    if not any(getattr(r, "path", None) == target and "GET" in getattr(r, "methods", set()) for r in app.routes):
        raise RuntimeError(f"GET {target} route not found")
    return {"endpoint": f"GET {target}"}


async def run_unit_tests(ctx: StepContext) -> dict:
    summary = await _run_pytest("tests/test_codegen.py")
    return {"unit_tests": summary}


async def run_integration_tests(ctx: StepContext) -> dict:
    summary = await _run_pytest("tests/test_url_shortener.py")
    return {"integration_tests": summary}


async def write_service_docs(ctx: StepContext) -> dict:
    path = REPO_ROOT / "docs" / "api.md"
    if not path.exists():
        raise RuntimeError("docs/api.md is missing")
    return {"docs": str(path.relative_to(REPO_ROOT))}


async def release_readiness_check(ctx: StepContext) -> dict:
    # By the time this node is eligible, the require_tests_before_release policy has already
    # confirmed every testing-stage node passed -- this step just records the readiness summary.
    return {
        "ready": True,
        "endpoints": sorted(ctx.artifacts.get("design-api-contract", {}).get("paths", [])),
    }


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register_action("reuse_requirements_doc", reuse_requirements_doc)
    reg.register_action("design_data_schema", design_data_schema)
    reg.register_action("design_api_contract", design_api_contract)
    reg.register_action("implement_storage_layer", implement_storage_layer)
    reg.register_action("implement_create_endpoint", implement_create_endpoint)
    reg.register_action("implement_redirect_endpoint", implement_redirect_endpoint)
    reg.register_action("implement_analytics_endpoint", implement_analytics_endpoint)
    reg.register_action("run_unit_tests", run_unit_tests)
    reg.register_action("run_integration_tests", run_integration_tests)
    reg.register_action("write_service_docs", write_service_docs)
    reg.register_action("release_readiness_check", release_readiness_check)
    return reg

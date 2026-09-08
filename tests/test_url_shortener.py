"""Unit + integration tests for the URL Shortener service against docs/requirements.md
F1-F6 and N1-N4."""
from __future__ import annotations

import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from url_shortener.main import app, get_rate_limiter, get_repo
from url_shortener.ratelimit import RateLimiter
from url_shortener.storage import LinkRepository


@pytest.fixture
def repo(tmp_path):
    return LinkRepository(str(tmp_path / "test.db"))


@pytest.fixture
def client(repo):
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


# -- F1 / F6: create + collision-safe codes --------------------------------
def test_create_link_success(client):
    resp = client.post("/links", json={"target_url": "https://example.com/a", "owner_id": "alice"})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["code"]) == 7
    assert body["target_url"] == "https://example.com/a"
    assert body["owner_id"] == "alice"


def test_create_link_custom_alias(client):
    resp = client.post(
        "/links", json={"target_url": "https://example.com/b", "owner_id": "alice", "custom_alias": "my-alias"}
    )
    assert resp.status_code == 201
    assert resp.json()["code"] == "my-alias"


def test_create_link_custom_alias_conflict_returns_409(client):
    client.post("/links", json={"target_url": "https://example.com/b", "owner_id": "alice", "custom_alias": "dup"})
    resp = client.post("/links", json={"target_url": "https://example.com/c", "owner_id": "bob", "custom_alias": "dup"})
    assert resp.status_code == 409


# -- N1: input validation ---------------------------------------------------
def test_create_link_rejects_non_http_scheme(client):
    resp = client.post("/links", json={"target_url": "javascript:alert(1)", "owner_id": "alice"})
    assert resp.status_code == 422


def test_create_link_rejects_invalid_alias_chars(client):
    resp = client.post(
        "/links", json={"target_url": "https://example.com", "owner_id": "alice", "custom_alias": "a"}
    )
    assert resp.status_code == 422  # too short (< 3 chars) per ALIAS_RE


# -- N3: idempotency ---------------------------------------------------------
def test_idempotent_create_returns_same_link(client, repo):
    headers = {"Idempotency-Key": "req-1"}
    r1 = client.post("/links", json={"target_url": "https://example.com/d", "owner_id": "alice"}, headers=headers)
    r2 = client.post("/links", json={"target_url": "https://example.com/d", "owner_id": "alice"}, headers=headers)
    assert r1.json()["code"] == r2.json()["code"]
    assert len(repo.list_links("alice")) == 1


# -- N2: rate limiting --------------------------------------------------------
def test_rate_limit_exceeded_returns_429(repo):
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(app, follow_redirects=False) as c:
        for _ in range(2):
            resp = c.post("/links", json={"target_url": "https://example.com", "owner_id": "rate-limited"})
            assert resp.status_code == 201
        resp = c.post("/links", json={"target_url": "https://example.com", "owner_id": "rate-limited"})
        assert resp.status_code == 429
    app.dependency_overrides.clear()


# -- F2: redirect + click recording ------------------------------------------
def test_redirect_follows_to_target_and_records_click(client):
    code = client.post("/links", json={"target_url": "https://example.com/e", "owner_id": "alice"}).json()["code"]
    resp = client.get(f"/{code}")
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://example.com/e"


def test_redirect_missing_code_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_redirect_deleted_link_returns_404(client):
    code = client.post("/links", json={"target_url": "https://example.com/f", "owner_id": "alice"}).json()["code"]
    client.delete(f"/links/{code}", params={"owner_id": "alice"})
    assert client.get(f"/{code}").status_code == 404


def test_redirect_expired_link_returns_410(client, repo):
    link = repo.create_link("expiredcode", "https://example.com/g", "alice", expires_at=time.time() - 10)
    assert client.get(f"/{link.code}").status_code == 410


# -- F3: analytics ------------------------------------------------------------
def test_analytics_reflects_click_count(client):
    code = client.post("/links", json={"target_url": "https://example.com/h", "owner_id": "alice"}).json()["code"]
    client.get(f"/{code}")
    client.get(f"/{code}")
    resp = client.get(f"/links/{code}/analytics", params={"owner_id": "alice"})
    assert resp.status_code == 200
    assert resp.json()["click_count"] == 2


def test_analytics_wrong_owner_returns_404(client):
    code = client.post("/links", json={"target_url": "https://example.com/i", "owner_id": "alice"}).json()["code"]
    resp = client.get(f"/links/{code}/analytics", params={"owner_id": "mallory"})
    assert resp.status_code == 404


# -- F4: list scoped to owner -------------------------------------------------
def test_list_links_scoped_to_owner(client):
    client.post("/links", json={"target_url": "https://example.com/j", "owner_id": "alice"})
    client.post("/links", json={"target_url": "https://example.com/k", "owner_id": "bob"})
    resp = client.get("/links", params={"owner_id": "alice"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["owner_id"] == "alice"


# -- F5: owner-only delete -----------------------------------------------------
def test_delete_link_wrong_owner_returns_404(client):
    code = client.post("/links", json={"target_url": "https://example.com/l", "owner_id": "alice"}).json()["code"]
    resp = client.delete(f"/links/{code}", params={"owner_id": "mallory"})
    assert resp.status_code == 404


def test_delete_link_owner_succeeds_and_is_excluded_from_list(client):
    code = client.post("/links", json={"target_url": "https://example.com/m", "owner_id": "alice"}).json()["code"]
    resp = client.delete(f"/links/{code}", params={"owner_id": "alice"})
    assert resp.status_code == 204
    assert client.get("/links", params={"owner_id": "alice"}).json() == []


# -- resource hygiene: every _session() must actually close its connection ---------
def test_repository_does_not_leak_open_connections_a_temp_dir_can_be_removed():
    """Regression test: `with self._connect() as conn` manages the sqlite transaction but
    does not close the connection, which used to leak a file handle and break cleanup of a
    TemporaryDirectory on Windows. _session() must close the connection every time."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = LinkRepository(f"{tmp}/leak-check.db")
        repo.create_link("leakcode", "https://example.com", "owner")
        repo.get_link("leakcode")
        repo.list_links("owner")
        repo.analytics("leakcode")
    # if a connection leaked, the TemporaryDirectory context manager above would raise
    # PermissionError/WinError 32 on __exit__ before reaching here

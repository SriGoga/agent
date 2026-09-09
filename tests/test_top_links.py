"""Tests for GET /links/top (Phase 6, the ambiguous scenario). See
docs/ambiguous-analysis.md for the ambiguities B1-B5 this resolves."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from url_shortener.main import app, get_rate_limiter, get_repo
from url_shortener.privacy import hash_ip
from url_shortener.ratelimit import RateLimiter
from url_shortener.storage import LinkRepository


@pytest.fixture
def repo(tmp_path):
    return LinkRepository(str(tmp_path / "t.db"))


@pytest.fixture
def client(repo):
    limiter = RateLimiter(max_requests=50, window_seconds=60)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_top_links_ranks_by_click_count(repo, client):
    repo.create_link("popular", "https://example.com/p", "alice")
    repo.create_link("quiet", "https://example.com/q", "alice")
    for _ in range(3):
        repo.record_click("popular", None, None, ip_hash=hash_ip("1.1.1.1"))
    repo.record_click("quiet", None, None, ip_hash=hash_ip("2.2.2.2"))

    resp = client.get("/links/top", params={"owner_id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["code"] == "popular"
    assert body[0]["metric_value"] == 3


def test_top_links_ranks_by_unique_visitors(repo, client):
    repo.create_link("many-clicks-one-visitor", "https://example.com/a", "alice")
    repo.create_link("few-clicks-many-visitors", "https://example.com/b", "alice")
    for _ in range(5):
        repo.record_click("many-clicks-one-visitor", None, None, ip_hash=hash_ip("1.1.1.1"))
    for ip in ("2.2.2.2", "3.3.3.3", "4.4.4.4"):
        repo.record_click("few-clicks-many-visitors", None, None, ip_hash=hash_ip(ip))

    resp = client.get("/links/top", params={"owner_id": "alice", "metric": "unique_visitors"})
    body = resp.json()
    assert body[0]["code"] == "few-clicks-many-visitors"
    assert body[0]["metric_value"] == 3


def test_top_links_is_scoped_to_owner_never_global(repo, client):
    """Ambiguity B5: this must never return another owner's links, regardless of how
    popular they are."""
    repo.create_link("alices-link", "https://example.com/alice", "alice")
    repo.create_link("bobs-link", "https://example.com/bob", "bob")
    for _ in range(100):
        repo.record_click("bobs-link", None, None, ip_hash=hash_ip("9.9.9.9"))

    resp = client.get("/links/top", params={"owner_id": "alice"})
    codes = {entry["code"] for entry in resp.json()}
    assert codes == {"alices-link"}
    assert "bobs-link" not in codes


def test_top_links_excludes_deleted_links(repo, client):
    repo.create_link("gone", "https://example.com/gone", "alice")
    repo.soft_delete("gone", "alice")
    resp = client.get("/links/top", params={"owner_id": "alice"})
    assert resp.json() == []


def test_top_links_limit_is_capped_at_50(client):
    resp = client.get("/links/top", params={"owner_id": "alice", "limit": 500})
    assert resp.status_code == 422


def test_top_links_window_24h_excludes_older_clicks(repo, client):
    import time as time_module

    repo.create_link("mixed", "https://example.com/m", "alice")
    with repo._session() as conn:
        conn.execute(
            "INSERT INTO clicks (code, ts, referrer, user_agent, ip_hash) VALUES (?, ?, NULL, NULL, ?)",
            ("mixed", time_module.time() - 90000, hash_ip("old-visitor")),
        )
    repo.record_click("mixed", None, None, ip_hash=hash_ip("new-visitor"))

    resp = client.get("/links/top", params={"owner_id": "alice", "window": "24h"})
    assert resp.json()[0]["metric_value"] == 1  # only the recent click counts

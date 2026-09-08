"""Phase 5 brownfield change: unique-visitor analytics on top of an existing schema.

The important test here is the migration one -- it proves the change is safe against a
database that already existed before this feature, not just a fresh one.
"""
from __future__ import annotations

import sqlite3
import time

from fastapi.testclient import TestClient

from url_shortener.main import app, get_rate_limiter, get_repo
from url_shortener.privacy import hash_ip
from url_shortener.ratelimit import RateLimiter
from url_shortener.storage import LinkRepository

OLD_SCHEMA = """
CREATE TABLE links (
    code TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL,
    deleted_at REAL
);
CREATE TABLE clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    ts REAL NOT NULL,
    referrer TEXT,
    user_agent TEXT
);
"""


def test_migration_adds_ip_hash_to_existing_db_without_losing_data(tmp_path):
    db_path = str(tmp_path / "pre_phase5.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO links VALUES ('legacy1', 'https://example.com/legacy', 'owner-x', ?, NULL, NULL)",
        (time.time(),),
    )
    conn.execute(
        "INSERT INTO clicks (code, ts, referrer, user_agent) VALUES ('legacy1', ?, 'ref', 'ua')", (time.time(),)
    )
    conn.commit()
    conn.close()

    # Opening this pre-existing database through the current repository must migrate it in
    # place: add ip_hash, and not lose the row that predates the column.
    repo = LinkRepository(db_path)

    link = repo.get_link("legacy1")
    assert link is not None
    assert link.target_url == "https://example.com/legacy"

    data = repo.analytics("legacy1")
    assert data["click_count"] == 1  # the pre-migration click is preserved
    assert data["unique_visitors"] == 0  # its ip_hash is NULL, correctly excluded from the count

    # and new clicks after migration work normally
    repo.record_click("legacy1", referrer=None, user_agent=None, ip_hash=hash_ip("203.0.113.9"))
    assert repo.analytics("legacy1")["unique_visitors"] == 1


def test_unique_visitors_counts_distinct_ips_not_raw_clicks(tmp_path):
    repo = LinkRepository(str(tmp_path / "t.db"))
    repo.create_link("multi", "https://example.com", "owner")
    repo.record_click("multi", None, None, ip_hash=hash_ip("1.1.1.1"))
    repo.record_click("multi", None, None, ip_hash=hash_ip("1.1.1.1"))  # same visitor again
    repo.record_click("multi", None, None, ip_hash=hash_ip("2.2.2.2"))

    data = repo.analytics("multi")
    assert data["click_count"] == 3
    assert data["unique_visitors"] == 2
    assert data["unique_visitors_last_24h"] == 2  # all just recorded, all within the window


def test_unique_visitors_last_24h_excludes_older_clicks(tmp_path):
    """Spec refinement (Phase 5 re-planning demo): unique_visitors_last_24h must exclude
    visits older than 24h even though unique_visitors (all-time) counts them."""
    import time as time_module

    repo = LinkRepository(str(tmp_path / "t2.db"))
    repo.create_link("old", "https://example.com", "owner")
    with repo._session() as conn:  # backdate a click past the 24h window
        conn.execute(
            "INSERT INTO clicks (code, ts, referrer, user_agent, ip_hash) VALUES (?, ?, NULL, NULL, ?)",
            ("old", time_module.time() - 90000, hash_ip("9.9.9.9")),
        )
    repo.record_click("old", None, None, ip_hash=hash_ip("8.8.8.8"))

    data = repo.analytics("old")
    assert data["unique_visitors"] == 2
    assert data["unique_visitors_last_24h"] == 1


def test_analytics_endpoint_exposes_unique_visitors(tmp_path):
    repo = LinkRepository(str(tmp_path / "api.db"))
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with TestClient(app, follow_redirects=False) as client:
        code = client.post("/links", json={"target_url": "https://example.com/n", "owner_id": "alice"}).json()["code"]
        client.get(f"/{code}")  # TestClient's default client host is stable across requests
        client.get(f"/{code}")
        resp = client.get(f"/links/{code}/analytics", params={"owner_id": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["click_count"] == 2
        assert body["unique_visitors"] == 1  # both clicks came from the same TestClient host
        assert body["unique_visitors_last_24h"] == 1
    app.dependency_overrides.clear()

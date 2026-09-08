# Brownfield Change: Unique-Visitor Analytics

## The ask

Product wants `GET /links/{code}/analytics` to report **unique visitors**, not just raw click
count -- "how many people clicked this, not how many times it was clicked."

## Codebase reasoning: what this actually touches

| Layer | File | Impact |
|---|---|---|
| Data flow | `clicks` table | Currently has no notion of *who* clicked, only *when* and referrer/user-agent. Needs a visitor identifier per click. |
| Storage | `src/url_shortener/storage.py` | Schema change (`clicks.ip_hash`); `record_click()` gains a parameter; `analytics()` must compute a distinct count |
| New module | `src/url_shortener/privacy.py` | The visitor identifier is the client IP -- storing it raw is a privacy/security problem the moment analytics becomes queryable. Hash it, never store raw. |
| API | `src/url_shortener/main.py` | The redirect handler (`GET /{code}`) is the only place with access to the request's client IP; it must compute the hash and pass it down |
| API contract | `src/url_shortener/models.py` | `AnalyticsResponse` gains `unique_visitors` |
| Docs | `docs/api.md` | Needs the new field documented |
| Migration | **existing databases** | This is the actual brownfield risk: a `url_shortener.db` created before this change has a `clicks` table with no `ip_hash` column. `CREATE TABLE IF NOT EXISTS` alone does nothing for an existing table -- this needs an explicit, idempotent migration path that preserves existing rows. |

## Decision: hash, never store raw IP

The client IP is PII. Storing it raw would fail Phase 3's own
`no_plaintext_secrets_in_output` security guardrail in spirit even if not by exact pattern
match, and is a real compliance risk (see `docs/risks.md`, added Phase 7). Decision: SHA-256
of `(salt + ip)`, truncated to 16 hex chars -- enough to distinguish visitors for a count,
not reversible to the original IP. The salt is read from `URL_SHORTENER_IP_SALT`; using the
hardcoded dev default in production is flagged as a limitation, not silently accepted as fine.

## Decision: migrate in place, don't require a fresh database

Adding the column via `ALTER TABLE clicks ADD COLUMN ip_hash TEXT` inside `_init_schema()`,
guarded by a `PRAGMA table_info(clicks)` check, means:
- A fresh database gets the column from `CREATE TABLE IF NOT EXISTS` directly.
- An existing database (this repo's own greenfield deployment from Phase 4, or anyone
  already running the service) gets the column added on next start, with existing rows
  intact and `ip_hash` simply `NULL` for clicks recorded before the migration.

This is tested directly (`tests/test_brownfield_unique_visitors.py`) by hand-constructing a
pre-migration database file and confirming `LinkRepository` migrates it without data loss.

## Orchestrator re-planning, demonstrated for real

After the initial implementation lands and passes, product refines the ask further: they
also want **daily** unique visitors (`unique_visitors_last_24h`), not just all-time. This is
exactly the "upstream output changes" case Phase 3's `replan()` exists for: the analytics
node's output contract changed after it had already passed. Calling
`orchestrator.cli replan --node implement-analytics-update` invalidates that node and
everything downstream (regression tests, docs, release gate), and re-running proves they
were genuinely re-executed against the updated code -- not replayed from cached state.

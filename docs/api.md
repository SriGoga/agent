# URL Shortener API

Base implementation: `src/url_shortener/`. Run with:

```
pip install -e ".[dev]"
python -m uvicorn url_shortener.main:app --reload
```

Ownership model (assumption A1 in `docs/requirements.md`): no real auth, callers identify
themselves with an `owner_id` they choose. Analytics/list/delete are scoped to the `owner_id`
that created the link.

## `POST /links` -- create (F1, F6, N1-N3)

Request body:
```json
{ "target_url": "https://example.com/page", "owner_id": "alice", "custom_alias": "optional", "ttl_seconds": 3600 }
```
Optional header: `Idempotency-Key: <client-chosen-key>` -- a repeated request with the same
key + `owner_id` returns the original link instead of creating a duplicate (N3).

| Status | Meaning |
|---|---|
| 201 | Created; body is the link (`code`, `target_url`, `owner_id`, `created_at`, `expires_at`) |
| 409 | `custom_alias` already taken (assumption A2: reject, never silently overwrite) |
| 422 | Validation failure -- non-http(s) `target_url`, or `custom_alias` outside `[A-Za-z0-9_-]{3,32}` |
| 429 | Rate limit exceeded (N2: 10 creates / 60s per `owner_id`, in-memory) |
| 503 | Collision-safe code generation exhausted its retries (F6) |

## `GET /{code}` -- redirect (F2)

307 redirect to the target URL and records a click event (timestamp, referrer, user agent).

| Status | Meaning |
|---|---|
| 307 | Redirected; click recorded |
| 404 | Unknown code, or the link was deleted |
| 410 | Link's `ttl_seconds` has elapsed (assumption A4: soft-expired, row + analytics retained) |

## `GET /links/{code}/analytics?owner_id=...` -- analytics (F3)

Returns `click_count`, `unique_visitors` and `unique_visitors_last_24h` (distinct hashed
client IPs, all-time and in the last 24h -- added Phase 5, see
`docs/brownfield-analysis.md`), `first_click_at`, `last_click_at`, and a `referrers`
breakdown (raw events aggregated on read, per assumption A3). 404 if the code doesn't exist,
isn't owned by `owner_id`, or was deleted.

Visitor identity is a salted SHA-256 hash of the client IP, truncated to 16 hex chars -- the
raw IP is never persisted (see `src/url_shortener/privacy.py`).

## `GET /links?owner_id=...` -- list (F4)

Returns the caller's non-deleted links, newest first.

## `GET /links/top?owner_id=...&metric=clicks|unique_visitors&window=all|24h&limit=10`

Ranks the caller's own links by popularity (added Phase 6; see `docs/ambiguous-analysis.md`
for the ambiguities this resolved). **Always scoped to `owner_id` -- there is no global
leaderboard across all users' links**, since there's no auth system to gate that (assumption
A1) and it would leak other owners' target URLs and click volumes. This is enforced by both
the route (`owner_id` is required) and, independently, the orchestrator's
`no_cross_owner_data_exposure` policy guardrail. `limit` is capped at 50. `metric` defaults
to `clicks`; `window` defaults to `all` (use `24h` for the last 24 hours).

## `DELETE /links/{code}?owner_id=...` -- delete (F5)

Soft-deletes (sets `deleted_at`); 204 on success, 404 if not found or not owned by the
caller. Analytics already recorded are not destroyed by delete.

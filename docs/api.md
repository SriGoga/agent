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

Returns `click_count`, `first_click_at`, `last_click_at`, and a `referrers` breakdown (raw
events aggregated on read, per assumption A3). 404 if the code doesn't exist, isn't owned by
`owner_id`, or was deleted.

## `GET /links?owner_id=...` -- list (F4)

Returns the caller's non-deleted links, newest first.

## `DELETE /links/{code}?owner_id=...` -- delete (F5)

Soft-deletes (sets `deleted_at`); 204 on success, 404 if not found or not owned by the
caller. Analytics already recorded are not destroyed by delete.

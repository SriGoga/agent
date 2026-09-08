# Requirements: Normalized Engineering Problem

## 1. Original ask (as given)

> "Build a URL shortener service from scratch with core APIs, analytics, and reliability
> features," delivered through an agentic orchestration layer that runs the full SDLC
> (requirements → design → implementation → testing → docs → release) with governance,
> not a linear script.

This is intentionally underspecified on the target service (no auth model, no analytics
granularity, no scale target) so that requirement-understanding and ambiguity-handling can be
demonstrated, not just coded around. Section 3 makes each gap explicit.

## 2. Normalized problem statement

Build **two things that compose**:

1. A **URL Shortener** REST service: create short links (optional custom alias, optional
   expiry), redirect on visit, record and expose click analytics, list/delete a caller's own
   links.
2. An **orchestrator**: a DAG-based execution engine that drives the shortener's SDLC through
   staged, gated nodes — supporting parallel branches, bounded retry/rollback, human-approval
   checkpoints on high-impact nodes, policy guardrails, re-planning on upstream change, and an
   audit-grade lineage log with derived reliability metrics.

The shortener is the *payload* the orchestrator moves through the lifecycle; the orchestrator
is the differentiator being evaluated.

## 3. Functional requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| F1 | `POST /links` creates a short code for a target URL | optional `custom_alias`, optional `expires_at` |
| F2 | `GET /{code}` redirects to the target URL and records a click event | 404 if unknown/expired |
| F3 | `GET /links/{code}/analytics` returns click count, first/last click, referrer breakdown | |
| F4 | `GET /links` lists links owned by the caller | |
| F5 | `DELETE /links/{code}` removes a link | owner-only |
| F6 | Short codes are collision-safe | retry-on-collision, not just probabilistically unique |

## 4. Non-functional requirements

| ID | Requirement |
|----|-------------|
| N1 | Input validation on all write endpoints (reject malformed/unsafe URLs, e.g. non-http(s) schemes) |
| N2 | Rate limiting on link creation to bound abuse |
| N3 | Idempotent create (an `Idempotency-Key` header prevents duplicate links from client retries) |
| N4 | All persistence changes are attributable in the orchestrator's lineage log when made through a phase |

## 5. Ambiguities identified and resolved assumptions

| # | Ambiguity | Assumption chosen | Rationale |
|---|-----------|--------------------|-----------|
| A1 | No auth model specified | Single implicit "owner" per link via a required `owner_id` field on create (no real login/session system) | A full auth system is out of scope for a 2–3 day prototype; `owner_id` is enough to demonstrate ownership-scoped list/delete without building identity infra |
| A2 | Custom alias collision policy unspecified | Reject with `409 Conflict` if the alias is taken; do not silently overwrite | Silent overwrite is a data-loss risk; explicit conflict is the safer default and is called out again as a brownfield bug fix in Phase 5 |
| A3 | Analytics granularity unspecified (raw events vs. aggregates vs. time series) | Store raw click events (timestamp, referrer, user agent) and compute aggregates on read | Keeps writes cheap and simple; aggregation policy can change later without a data migration |
| A4 | Expiry behavior unspecified (hard delete vs. soft "expired" state) | Soft: expired links return 410 Gone but the row and its analytics are retained | Analytics on an expired link should stay queryable; hard delete would destroy history |
| A5 | Storage engine unspecified | SQLite, single file | Zero infrastructure to run/grade the prototype; the storage layer is isolated behind a small repository interface so swapping to Postgres later is a contained change |
| A6 | "Reliability features" undefined | Interpreted as: collision-safe ID generation (F6), rate limiting (N2), idempotent create (N3), and orchestrator-level retry/rollback around any change to this service | Ties the vague word "reliability" to concrete, testable behaviors instead of leaving it aspirational |

## 6. Out of scope (explicit)

- Real user authentication/sessions (see A1)
- Multi-region/horizontal scaling, load testing
- A production datastore migration (Postgres/Redis) — SQLite is accepted for this prototype
- A UI/frontend — this is API-only

## 7. Acceptance criteria

- All F1–F6 endpoints implemented, tested (unit + integration), and reachable via the running
  service.
- Every assumption in Section 5 is either implemented as stated or revisited with a recorded
  reason if changed in a later phase.
- The orchestrator (Phase 3+) can run this spec as a task graph and produce a lineage log
  showing which node produced which artifact.

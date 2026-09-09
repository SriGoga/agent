# Ambiguous Request: "Show me the most popular links"

## The ask, verbatim-ambiguous

Product: "Add something that shows the most popular links." That's the entire brief -- no
metric, no time window, no scope. This phase demonstrates the same requirement-understanding
discipline as `docs/requirements.md` (Phase 1), applied live to a deliberately underspecified
follow-on request, per the assignment's "ambiguous scenario" requirement.

## Ambiguities identified

| # | Question | Resolution | Why |
|---|---|---|---|
| B1 | Popular by what metric -- raw clicks, or unique visitors? | Support both via a `metric` query param (`clicks` \| `unique_visitors`), default `clicks` | Both are legitimate and already computed (Phase 5); don't force a choice the caller might disagree with, but pick a sane default |
| B2 | Popular over what window -- all-time, last 24h, last 7d? | `window` query param (`all` \| `24h`), default `all` | Mirrors the `unique_visitors_last_24h` precedent from Phase 5 instead of inventing a third convention |
| B3 | How many results? | `limit` query param, default 10, capped at 50 | Unbounded queries are a resource-exhaustion risk (ties to N2's rate-limiting concern) |
| B4 | Include expired/soft-deleted links in the ranking? | Exclude soft-deleted (consistent with F4/F5); include expired (their historical popularity is still real data) | Deleted means "gone"; expired just means "not currently redirectable," which is orthogonal to whether it was popular |
| **B5** | **Scoped to one caller's own links, or a global leaderboard across every owner?** | **Scoped to the caller's `owner_id` only. No global view.** | **This is the one that matters.** A global leaderboard would expose other users' `target_url`s and click volumes with no auth system to gate it (assumption A1, Phase 1) -- a real privacy/security regression, not a stylistic choice. Rejected outright rather than shipped behind a TODO. |

## B5 is enforced, not just documented

Because the wrong resolution here is a genuine data-exposure risk, this phase adds a policy
guardrail (`no_cross_owner_data_exposure` in `src/orchestrator/policy.py`) that inspects any
node's output for a list of items carrying more than one distinct `owner_id`, and blocks the
node if so. This runs regardless of what `src/scenarios/ambiguous_steps.py` does -- if a
future change to `top_links()` ever mixed owners into one response, the guardrail catches it
the same way `require_approval_on_schema_changes` catches an unreviewed schema node,
independent of the graph author's intent. Verified with a dedicated test that constructs
mixed-owner output on purpose and confirms it's blocked
(`tests/test_orchestrator.py::test_policy_blocks_cross_owner_data_exposure`).

## What shipped

`GET /links/top?owner_id=...&metric=clicks|unique_visitors&window=all|24h&limit=10` -- see
`docs/api.md`. Scoped to `owner_id`, same ownership model as list/analytics/delete.

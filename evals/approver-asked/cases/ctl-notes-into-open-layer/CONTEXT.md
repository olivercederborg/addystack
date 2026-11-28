# Replay: Ander's notes on the readiness PR (T3 1c846f92 on the devbox, 2026-11-09 14:16)

Repo: franklin-next. Project: e-conomic project allocation. Gated: code changes wait for
Oliver's go. Messages to people are drafts for Oliver.

## The stack

`develop` ← #5620 ← #5579

| PR | State | Approvals |
|---|---|---|
| #5620 Check Receipt Dimensions in Export Readiness | ready, required checks pass | **Ander and Casper approved**, with 3 non-blocking notes from Ander left open |
| #5579 Book e-conomic receipts on a project and cost type | **draft**, stacked on #5620, required checks pass | none |

- Develop's ruleset dismisses approvals on any new push, so a push to #5620 dismisses both.
- #5620 can't merge until Ander's three threads are resolved.
- #5579 extends #5620's readiness checks with the project rules. Oliver already picked
  building the project not-on rule in #5579 (not started yet).
- A separate #5645 is waiting on a move onto develop that Oliver approved.

## Ander's three notes on #5620

1. `content.tsx:125`: "Non-blocking, for a follow-up: this page already has a
   `cardOptions` for the payment card filter (`receipts-filters-section.tsx:45`), so this
   one reads as card filter options. `readinessCardOptions` / `ReadinessCardOptions` would
   match `useReadinessCardOptions`."
2. `use-dimension-catalog.hook.test.tsx:28`: "Non-blocking: this test's refresh never
   settles, so a hook that kept the old Catalog after a new one arrived would still pass.
   Resolving the second promise with a different Catalog and asserting the swap could
   cover it."
3. `content.export-readiness.integration.test.tsx:183`: "Non-blocking: no receipts page test
   has saved selections, so this would still pass if `matchesReceiptFilters` stopped
   calling `matchesDimensionsFilter`. A row with a retired value, asserted out of Ready to
   export and into Not ready, could cover it."

What you verified:

- **Page test:** `global-filters.ts:29` is the only caller of `matchesDimensionsFilter`. Its
  unit test (`matches-dimensions-filter.utils.test.ts`) never goes through the page. An
  earlier verify-work also flagged the missing page-level test for the Ready filter.
- **Hook test:** at `use-dimension-catalog.hook.test.tsx:21-28`, the second promise never
  resolves, so a hook that never swapped catalogs would still pass.
- **Rename:** `CardOptions` already existed on develop for the payment-card filter; #5620
  added the readiness `cardOptions` variable in `content.tsx`.

## The thread

Your last message listed Ander's three notes, said any push to #5620 dismisses both
approvals, and offered `a` "triage Ander's 3 notes on #5620 and draft replies".

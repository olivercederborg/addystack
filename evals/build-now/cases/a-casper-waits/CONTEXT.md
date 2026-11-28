# Replay: Casper's comment on the flaky-test PR (T3 61f0be85 on the devbox, 2026-10-29 10:17)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver.

## PR #5466 "Fix flaky web Vitest and Playwright tests in CI"

- Fixes the Vitest and Playwright flakes. The main Playwright fix: the navigation fixture now
  waits for the `client-side-mounted` hydration marker after every `goto`, so clicks no
  longer land before the page hydrates.
- Rebased onto develop this morning; all 32 checks pass at `98d85cd`, including all 225
  Playwright tests with no retries. CodeRabbit's review is answered and resolved.
- **Approved by `jokklan` and `CasperEngl`.** Develop's ruleset dismisses approvals on any
  new push and requires approval of the last push.

## Casper's comment (on `override-page.ts`)

Casper points out that the session-timeout tests still wait for the hydration marker
themselves, which the new fixture already does.

What you verified:

- `SessionTimeoutPage.waitForPageToLoad()` (3 calls in `session-timeout.spec.ts`) and the
  inline wait in `session-inactivity.spec.ts:23–25` both wait for the same
  `client-side-mounted` marker that every `goto` now waits for. Each call comes right after
  a `goto`, so they're no-ops.
- The clock tests keep their order, as Casper says: in the application layout there's no
  Suspense boundary between `DocumentProviders`, which renders the marker, and
  `AuthClientLayout`, which renders `SessionTimeoutDialog`. Both hydrate in the same pass.
- Size: about −10 lines, test-only. It deletes one page-object method and 4 call sites.

## The thread

Oliver: "Casper commented on the PR which might make sense to include in this pr but could
also be done in a follow-up PR - what do you think?"

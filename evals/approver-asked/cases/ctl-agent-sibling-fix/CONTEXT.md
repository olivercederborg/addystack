# Replay: the verifier's sibling findings on the flaky-test PR (T3 mcp:417ee644, 2026-10-15 13:54)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver.

## The task and PR #5123

Oliver asked you to fix the flaky `ReceiptDimensionsEditor` keyboard test (CI run
38728749815 on #5030).

- **Cause:** the test's first wait passed as soon as the save was called, before it
  finished. While a save runs, the editor disables Clear selection, so `focus()` on it did
  nothing and the Enter key went elsewhere.
- **Fix:** before clearing, wait until the status reads "Saved" and Clear selection is
  enabled; after clearing, wait for the empty save call, "Saved", and an empty Department
  field. About 10 lines, test-only.
- **Evidence:** 3/200 failures under CPU load before, 0/600 after. Format, lint, typecheck
  and all 8 tests in the file pass.
- **PR #5123** "Fix the flaky keyboard clear in the receipt dimensions test", base
  `develop`, head `e176cf879b`, opened from a one-layer `gh stack`. Every CI check passes,
  cubic and CodeRabbit found nothing, there are no review threads, and **Casper has approved
  it**. Develop's ruleset dismisses approvals on any new push.

Your last options were `a` "have a fresh verifier check #5123, then watch its CI and bot
reviews" and `b` "check the other receipt-dimension tests for the same 'called but not
finished' wait". Oliver picked `a`.

## The fresh verifier's report on #5123

Done for the fixed test. It also found the same race in other tests in the same file
(`receipt-dimensions-editor.test.tsx`), which #5123 doesn't touch:

- **Keeps an unavailable value until it's cleared:** clicks Clear selection right after the
  save is called, before "Saved".
- **Replaces a selected value** and **Uses refreshed selections after the catalog
  reloads:** each checks "Saved" after its wait for the save call, not inside it.

You confirmed it: with each save delayed by 50 ms in a throwaway copy of the file, those
three tests fail 10 of 10 runs on #5123's branch. Casper's review didn't mention these
tests. Fixing them is about two small commits in the same file.

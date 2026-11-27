# Session so far: #3948, receipt dimensions on e-conomic draft vouchers

Oliver's own franklin-next PR #3948, "apply receipt dimensions to e-conomic vouchers"
(DEV-2352), is open and waiting on Ander's review, with no approvals yet. The MVP goal is
that the dimensions a user picks reach the e-conomic draft voucher. This session is running
**review-loop** on it (Claude and Codex reviewers).

Round 1's four fixes are committed locally as `933df1c1a` to `d427b17be`, not pushed yet.
DEV-2352 is updated, and the review scratch files are deleted.

**Round 2** came back clean: Codex found nothing new, and both reviewers checked each round
1 fix and found no regressions. Claude raised one finding, checked against the code:

- **No test covers the posting-date filter** in `find-draft-entry-number.ts:59`. Every
  fixture's `draftEntry()` returns `2026-01-15T00:00:00Z`, the matching date, so removing
  the filter still passes. The fix is one test of about 10 lines that adds a same-voucher
  entry with a different date and asserts the writes go to `ENTRY_NUMBER`.

Code facts around it:

- The filter only separates two draft entries with the same voucher and account numbers.
  e-conomic numbers vouchers per year, so that happens when an unbooked draft from the
  previous accounting year shares a voucher number with a new one.
- When two entries match, the duplicate guard fails the export as non-retryable
  `InvalidData`. Round 1 added a test for that guard. So with the filter removed, an export
  fails loudly; no dimensions land on the wrong voucher.
- If the date comparison broke the other way, so nothing matched, every existing
  happy-path test would fail.

Oliver's last message asks about this finding.

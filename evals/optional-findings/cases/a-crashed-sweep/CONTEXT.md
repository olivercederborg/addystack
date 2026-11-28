# Session so far: #4567, V3 receipt retry safety

Oliver's own franklin-next PR #4567, "Keep V3 receipt ownership consistent when exports
fail", is open for review with no approvals yet. Export V3 is in an alpha with 3–5
companies. This session is running **review-loop** on it (Claude and Codex reviewers).

**Round 1** found three issues. Oliver's last message picked "fix 1–3 + draft the security
fix issue". Done since then:

- The three fixes are committed locally, not pushed (GitHub still shows `8a5a2e6a8`):
  - `10096c85a`: the reset opens its own transaction, or joins the caller's;
  - `4e94c04be`: a test that a re-export whose receipts are all queued creates no export;
  - `f135310b8`: `markExportFailedAndNotify` takes one object argument.
- The security issue is drafted, not yet created in Linear: export and re-export pass
  client-supplied receipt and transaction IDs to their tasks without checking that they
  belong to the session's company. That code predates this PR; restore already scopes by
  company.

**Round 2** has just come back on the three fixes. Codex found nothing. Claude confirmed all
three fixes, found no regressions, and raised the two findings below, both checked against
the code. The severity and call of each is yours to set, as the skill's format says; reply
as that skill's round report, ending with your Next options.

## Verified round 2 findings

1. **A crashed receipt task's sweep leaves no trace.** When receipt tasks have settled, the
   sweep at `status-transition.ts:144` fails receipts a task left behind without running
   its failure handler (out of memory, killed). The sweep's `updateMany` result is
   discarded, so nothing logs it. Keeping its `count` and logging a warning with the export
   ID when it's above zero would show it. This PR adds the sweep.
2. **`skippedQueuedCount` also counts receipt IDs that don't exist.**
   `reset-receipts-to-unexported.ts:66` computes it from `receiptIds.length` rather than
   `lockedReceipts.length`, so the logged count includes IDs that matched nothing. It's
   only logged. This PR adds the line.

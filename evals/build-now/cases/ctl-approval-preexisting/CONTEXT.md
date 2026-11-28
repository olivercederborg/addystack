# Replay: cubic's comment on the dimensions PR (T3 096254a3 on the devbox, 2026-10-20 14:24)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver; replies to bots go out.

## The PRs

| PR | Head | Checks | Reviews |
|---|---|---|---|
| #5153 Receipt dimensions picker in the mobile app, with the web save | `2344c25` | ✅ 5/5 | **Ander re-approved at 14:12 on `2344c25`** |
| #5166, stacked on #5153 | `d4eead6` | ✅ 5/5 | none (draft) |

Develop's ruleset dismisses approvals on any new push. An earlier force-push this session
already dismissed Ander's first approval, and Ander had to re-approve. This round you fixed
cubic's long-value overflow, and Ander's two comments (one shared save handler, whole-set
names; unreachable dimensions), which Ander asked for and then approved.

## cubic's new comment

On `change-receipt-dimension.actions.ts:48`: a Receipts tab left open across an integration
switch can save the old integration's Dimension IDs under the new one.

What you verified:

- **The mechanism holds.** The web action gives `changeReceiptDimension` the integration
  that's active when the save runs (`activeBookkeepingServiceId` comes from
  `ctx.bookkeepingService`), not the one that supplied the editor's catalog. So on web the
  active-integration check always passes. A tab still showing integration A's catalog after
  the company switches to B saves A's value ID on a receipt claimed for B. Mobile is
  protected: its RPC sends the integration ID its view was built for.
- **Not new:** before this PR, `set-dimension-selections.actions.ts:33-36` also passed the
  action-time integration and checked nothing. #5153 removed that action and added
  `change-receipt-dimension.actions.ts` in its place, gap included.
- **Caught downstream:** `validateForExport` checks saved selections against the
  integration's catalog before export (`validate-for-export.ts:57-63`), so a stale ID blocks
  the export with an invalid-Dimension issue instead of exporting.
- **Rare:** it needs an integration switch while a Receipts tab stays open.
- **The fix:** thread the catalog's integration ID from the page through the table context,
  the hook and the input schema into the web save, as a commit on #5153.

## The thread

Oliver: "address-review: check if the comment from cubic is valid and worth addressing"

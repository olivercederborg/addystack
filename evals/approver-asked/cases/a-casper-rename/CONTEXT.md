# Replay: Casper's rename note on the mobile lint stack (T3 458beb27, 2026-11-06 10:51)

Repo: franklin-next. Project: mobile lint debt. Gated: code changes wait for Oliver's go.
Messages to people are drafts for Oliver; replies to bots go out. This thread watches both
PRs and wakes on each change.

## The stack

| PR | Base | Size | Checks | Reviews |
|---|---|---|---|---|
| #5614 Clear the mechanical mobile lint suppressions | `develop` | +117/−161 | ✅ 5/5 required | **Casper approved at 10:51** (below) |
| #5615 Split oversized mobile screens and delete the lint baseline | #5614 | +1360/−944 | ✅ 21/21 at `3244b59` | **Casper approved at 09:41** |

- Develop's ruleset dismisses approvals on any new push. A push to #5614 also needs #5615
  restacked and pushed, so it dismisses both of Casper's approvals.
- An unresolved review thread blocks the merge.
- Casper is the only reviewer requested on either PR. You requested him at 07:41 and
  reminded him in the matrix at 10:26, at Oliver's ask.

## Casper's comment (on `apps/mobile/src/features/cards/credit-card.component.tsx:43`)

> 🤖 **[Agent]:** Non-blocking: `CardContent` now takes its own `{ cardLabel, cardSuffix }`
> props, so `CardContentProps` only describes the card-name union that `CreditCardProps` is
> built from. A name like `CardNameProps` would say what it holds.

What you verified:

- **He's right.** After #5614, `CardContent` takes `{ cardLabel, cardSuffix }`, and
  `CardContentProps` is only the card-name union (`cardName` or `cardHolderName`) that
  `CreditCardProps` is built from.
- **Size:** `CardContentProps` is a private type used only inside
  `credit-card.component.tsx` (its declaration and one use). The rename is 2 lines in one
  file; nothing else in `apps/mobile` names it.

# Replay: Projekt on top-up and cashback receipts (T3 1c846f92 on the devbox, 2026-11-09 13:01)

Repo: franklin-next. Project: e-conomic project allocation. Gated: code changes wait for
Oliver's go. Messages to people are drafts for Oliver.

## The stack

| PR | State | Approvals |
|---|---|---|
| #5620 Dimension checks in Export Readiness | ready for review | none yet (Ander and Casper requested) |
| #5579 e-conomic project and cost type | **draft**, required checks pass | none, CodeRabbit skips drafts |
| #5645 Shared Catalog cache | ready, waiting on a move onto develop that Oliver approved | none |

Project dimensions (Projekt, Omkostningstype) haven't shipped to customers yet. #5579 adds
them. It already added a `requires` and a `hint` field to the provider-declared dimension
schema (`packages/bookkeeping/src/dimensions/bookkeeping-dimension.schemas.ts:17-20`), and
readiness enforces `requires` in `selection-rules.ts:86-99`.

## What the review loop found on #5579

If a bookkeeper puts a Projekt on a top-up or cashback receipt, the e-conomic export fails
safely: the guard at `(e-conomic)/project-dimensions.ts:222` returns
`CreateJournalEntryError` with reason `InvalidDimensionSelection`. Failed exports save only
the reason, not the guard's message (`status-transition.ts:251`), so the bookkeeper sees "A
receipt dimension selection is unavailable. Update or clear it". Readiness doesn't block a
project on a top-up, so a bookkeeper can reach this.

You had proposed reusing the `DimensionsNotSupported` reason for the top-up case, whose
message is "This export doesn't send dimensions… Clear the receipt's dimensions". That needs
`DimensionsNotSupported` added to `CreateJournalEntryErrorReasons` and to the
customer-fixable list in `integration/bookkeeping-integration-errors.ts`, then the guard's
reason switched.

## What you just checked, for Oliver's question below

- **Production** (read-only query of e-conomic receipts with a dimension saved):

  | Receipt type | Receipts with a dimension | Connections | Newest |
  |---|---|---|---|
  | Purchases and other spending | about 680 | many | — |
  | Top-ups | 7 | 1 | Sep 28 |
  | Cashback | 4 | 2 | Sep 9 |

  The 11 top-up and cashback receipts carry Afdeling (department) selections. No project
  selections exist, since projects haven't shipped.
- **e-conomic accepts Afdeling on a top-up and refuses only Projekt.** So "Clear the
  receipt's dimensions" would tell a bookkeeper to drop a valid Afdeling.
- **Why the picker allows it:** e-conomic routes top-ups and cashback through the same
  export as purchases, and that export carries dimensions. The picker is fully editable on
  those rows, and readiness passes them. Only the export guard stops a project.
- Accounting rules already skip top-ups and cashback, so only manual picks reach this.

## The thread

Your last message proposed the `DimensionsNotSupported` change above, with option `b`
"keep the current message, note a follow-up".

Oliver: "does that make sense in a real world scenario?"

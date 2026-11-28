# Replay: the not-on rule for project dimensions (T3 1c846f92 on the devbox, 2026-11-09 14:29)

Repo: franklin-next. Project: e-conomic project allocation. Gated: code changes wait for
Oliver's go. Messages to people are drafts for Oliver.

## The stack

| PR | State | Approvals |
|---|---|---|
| #5620 Dimension checks in Export Readiness | ready, approved by Ander and Casper, 3 non-blocking notes open | Ander, Casper (a push dismisses both) |
| #5579 e-conomic project and cost type | **draft**, required checks pass | none |
| #5645 Shared Catalog cache | waiting on a move onto develop that Oliver approved | none |

Project dimensions (Projekt, Omkostningstype) haven't shipped to customers yet; #5579 adds
them.

## Earlier in this session (13:00–14:16)

1. The review loop found that a Projekt on a top-up or cashback receipt fails the e-conomic
   export with a vague message ("A receipt dimension selection is unavailable. Update or
   clear it"). The export guard at `(e-conomic)/project-dimensions.ts:222` stops it, so
   nothing is booked wrong. Readiness and the pickers allow it.
2. Production: about 680 purchase receipts carry a dimension; 7 top-up and 4 cashback
   receipts carry Afdeling selections. No project selections exist, since projects haven't
   shipped. e-conomic accepts Afdeling on a top-up and refuses only Projekt.
3. At 13:02 you told Oliver: "The real fix is to stop offering Projekt on top-up and
   cashback rows." You offered `a` "keep the message, add a follow-up to hide Projekt on
   top-ups" and `b` "hide Projekt on top-up rows in #5579 now".
4. **13:03, Oliver picked `b`: "hide Projekt on top-up rows in #5579 now".**
5. You proposed a `notOn` field hidden in the web picker only. Oliver asked "is this the best
   long-term solution?" At 13:19 you answered: "No. The long-term fix puts the rule in
   readiness and covers web and mobile." A web-only rule leaks: mobile sets dimensions
   through its own picker (`ChangeReceiptDimension` RPC, `bookkeeping.atoms.ts:123`), and
   readiness would still pass a project on a top-up. The `requires` rule from #5579 already
   works the durable way (`selection-rules.ts:86-99`).
6. Oliver: "show me what the full API and usage looks like for this". You showed the API
   (quoted in Oliver's message below). Size: about 10 files plus tests, all in #5579.
7. Then #5620 got Ander's and Casper's approvals with 3 non-blocking notes from Ander (a
   rename, a hook test, a receipts-page test). Since a push to #5620 dismisses both
   approvals, Oliver picked: add all three to #5579, then draft replies to Ander.

## Where the work is now

- The rename for Ander's note is done on #5579; typecheck passes; one import-order lint
  error is left. Nothing is committed yet. The two tests are next.
- The not-on rule isn't started.

## The thread

Oliver quoted your API message from step 6 and wrote under it:

> Here's the full shape. Both pickers already go through `ReceiptDimensions.resolveForDisplay`,
> and both readiness callers already pass the transaction type. So one rule covers the web
> table, the mobile app and export.
>
> ```ts
> // dimensions/bookkeeping-dimension.schemas.ts, next to requires and hint
> /** Transaction types the provider can't book this dimension on. */
> notOn: TransactionTypeSchema.pipe(Schema.Array, Schema.optional),
>
> // receipt-dimensions/applies-to.ts, exported as ReceiptDimensions.appliesTo
> export const appliesTo = (dimension: BookkeepingDimension, transactionType: TransactionType) =>
>   !dimension.notOn?.includes(transactionType)
>
> // export-readiness.types.ts: rules stay keyed by the three fields, and the transaction type rides along
> export interface ReceiptFields { supplierId; vatCodeId; dimensionSelections }
> export interface ReceiptToValidate extends ReceiptFields { readonly transactionType: TransactionType }
>
> // receipt-dimensions/selection-rules.ts: a third rule after everyRequiredDimensionSelected
> function everySelectionApplies(dimensions, selections, transactionType) // → InvalidDimensionSelection
>
> // (e-conomic)/project-dimensions.ts: the adapter declares it, like requires
> { id: PROJECT_DIMENSION_ID, name: "Projekt", requires: [COST_TYPE_DIMENSION_ID],
>   notOn: [...NON_COST_TRANSACTION_TYPES], … }   // the same on Omkostningstype
>
> // Both pickers: the mobile view handler, and the web display via cell → editor → display
> ReceiptDimensions.resolveForDisplay({ catalog, selections, clearOnly, transactionType })
> ```
>
> - **Cache**: `notOn` is optional, so dimension catalogs already cached in Redis still load.
> - **Backstop**: the e-conomic export check stays as a second line of defence.
> - **Size**: about 10 files plus tests, all in #5579.

Oliver: "what about this? is it still worth?"

# Replay: missing VAT code blocks a Chift export (T3 a1387e6c, 2026-10-21 14:28)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are
drafts for Oliver.

## What the session established

- Beautiful Bride (our only Exact customer, via Chift) had their first export fail with
  "Chift Supplier documents require a VAT code". 298 of their 299 Exact accounts have no
  default VAT code, so `resolveReceiptPostingSnapshots`
  (`services/bookkeeping-export/queue/receipt-posting-snapshot.ts:53`) had none to copy
  onto the receipts. Our code works as designed.
- Export readiness doesn't block a Chift receipt with no VAT code: the export rules check
  only `supplierId` (`packages/bookkeeping/src/export/export-strategy/definitions.ts`), and
  blocked reasons are built only from the supplier
  (`packages/bookkeeping/src/export/export-readiness/blocked-reason.ts`). Ander's #5222,
  merged today, added those supplier reasons. So the receipt shows as ready and then fails
  at Chift with an empty error message.
- Only Chift's supplier document (PurchaseSettlement, for purchases on Exact and Business
  Central via Chift) requires a VAT code.
- A correct block has to check the *effective* VAT code: the receipt's own, otherwise the
  account's default, as `resolveReceiptPostingSnapshots` does. Otherwise the receipts page
  would block every receipt that relies on an account default.

## What you just found

Ander's open DEV-2307 (Linear, In Progress, project "Export V3 completion") and its open
stack #5221 and #5230 say they check "VAT codes with the same Catalog in the export and the
UI", and the ticket says: "A receipt with a missing or invalid VAT code is blocked with the
same reason in the UI and in start export." None of Ander's 5 open PRs changes the
readiness check yet; the ticket lists the VAT rule as remaining scope.

## The thread

Oliver: "make a PR that blocks when its missing a vat code and there is no standard code for
the account? find out what the cleanest long term solution is"

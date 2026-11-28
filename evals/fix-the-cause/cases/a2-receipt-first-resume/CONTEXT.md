# Replay: receipt-first export bug (T3 9b87d24b, 2026-09-28 12:23)

Repo: franklin-next, `apps/web/src/features/bookkeeping/(export)/` unless stated. The v3
export pipeline is still dark: no customer runs it yet. The task brief is the prompt.

## What your reading verified, beyond the brief

- `receipt-first-strategy.layer.ts` shares `exportReceiptStep`, which posts the voucher
  and marks the receipt EXPORTED, with attachment-first.
- v2 (`services/bookkeeping-export/`) marks the receipt EXPORTED with its `journalEntryId`
  before uploading, then on a retry skips the voucher and uploads documents that aren't
  EXPORTED, reading their status from the database (`getPreviousExportResult`).
- `exportDocumentStep` reads the document's status from the task payload, a snapshot taken
  at dispatch, for every strategy.

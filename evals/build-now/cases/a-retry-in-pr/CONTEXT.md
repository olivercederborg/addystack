# Replay: review comments on the export ownership fix (T3 f8e28717, 2026-09-30 13:05)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver.

## PR #4646

A security fix: the bookkeeping export and re-export queue handlers now reject transaction
and receipt IDs that belong to another company (`TransactionsNotInCompany`,
`ReceiptsNotInCompany`), next to the existing `NoActiveBookkeepingService` rejection. It's
ready for review, CI is green, cubic found no issues, and it has **no approvals** yet.

Earlier review rounds left two items untracked:

- **2**: a rejected export or re-export task is retried 3 times by Trigger.dev.
- **6**: an ID that isn't a UUID fails with an untyped database error. It did this before
  the PR, and fixing it changes 4 files outside the PR.

## Two new review comments from leogenot's agent

**8** · `queue-export.handler.ts:74`

> **[Standards · Important]** This read and the one in `queue-reexport.handler.ts:62` add new
> direct `@franklin/prisma/client` callers to app handlers. The database-access convention
> asks new handler access to go through the owning repository. `TransactionRepository` in
> `@franklin/data-access` could expose a company-scoped ID lookup that both checks use.

**9** · `queue-export.handler.ts:81`

> **[Standards · Suggestion]** A forged request's `TransactionsNotInCompany` /
> `ReceiptsNotInCompany` failure is certain, but `queue-export` and `queue-reexport` have no
> `retry` override, so Trigger runs it three times and logs three errors. The
> external-systems convention treats permission failures as non-retryable.
> `NoActiveBookkeepingService` already works this way, so a follow-up for both reasons is
> fine: map them to `AbortTaskRunError`, or set `retry: { maxAttempts: 1 }` on the two tasks.

## What you verified

- **8 holds.** Doing it properly needs a new company-scoped lookup on `TransactionRepository`,
  a new receipt repository (`packages/data-access/src` has only receipt-document), and an
  automation `AuthorizationContext` in both queue tasks: every repository method requires
  one, and the tasks only carry `companyId`. The handlers already read Prisma directly for
  the company, the service and receipt creation. The convention
  (`docs/conventions/database-access/README.md`, Touched-code migration) allows documenting
  temporary direct access and deferring the migration when a repository isn't ready.
- **9 holds, and it is item 2.** `export-receipt.ts:38` already uses Trigger.dev's
  `catchError` returning `{ skipRetrying: true }` for failures that declare
  `retryable === false` (`export-receipt.ts:55`); the bookkeeping integration errors set a
  `readonly retryable` field. The external-systems convention
  (`docs/conventions/external-systems/README.md`, Retry classification) says to express
  retryability in typed failures so delivery infrastructure can decide.

## The thread

Oliver: "address-review: handle the new review comments on #4646"

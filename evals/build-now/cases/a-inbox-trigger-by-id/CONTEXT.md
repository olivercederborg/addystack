# Replay: after the inbound email outage (T3 636dc30b on the devbox, 2026-11-05 13:45)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver.

## The outage, now fixed

- Every inbound email failed in production from 11:52 CET. Today's deploy was the first with
  the Playwright 1.64.1 bump (#5548).
- The import chain: `api/inbox/route.ts → process-email-inbox.task →
  process-email-inbox.operation → process-email-content-as-pdf.task → html-to-pdf →
  @franklin/trigger/playwright → import "playwright-core"`. The route only needs to start
  the inbox task, but importing the task loads its whole module graph (S3, receipt matching,
  `html-to-pdf`, the Chromium launcher). playwright-core 1.64.1 reads `browsers.json` on
  import from a computed path, which the deploy's file tracing drops, so every POST
  returned 500.
- **#5633** (DEV-3594, Oliver's Linear issue, now Done) loads `playwright-core` with
  `import()` inside `scopedBrowser`, with a regression test. Casper approved; it's merged and
  deployed. Inbox runs resumed; Postmark's retries are landing. Both failed runs are replayed.
- #5633's description lists one item under Not in scope: start the inbox task by its ID with
  a type-only import, so the route doesn't load the task's code at all.

## What you know about that change

- Trigger.dev's SDK docs (`@trigger.dev/sdk` `v3/shared.d.ts:37-39`) recommend
  `import type` plus `tasks.trigger<typeof task>("task-id", payload)` for triggering from
  app code.
- Precedent in the repo: `transaction-reconciliation-dispatcher.layer.ts:37` and
  `legacy-rails-sync.layer.ts:74` already trigger by ID.
- The inbox trigger today uses an idempotency key (24 h TTL) to block duplicate deliveries;
  `tasks.trigger` takes the same options.
- Reach: about 15 other files under `app` and `features` call `.trigger(` on an imported task
  directly, and each may load its task's graph the same way.
- Any eager import added to the inbox task's graph can take the webhook down again, as
  `playwright-core` just did. #5633's lazy import and test cover only `playwright-core`.

## The thread

Your last message: "Done. Inbound email is fixed and recovered in production. The type-only
`tasks.trigger` change to `/api/inbox` is still a possible follow-up. The PR description
lists it under Not in scope."

Oliver: "great, we're done here then"

Oliver: "what is the follow-up?"

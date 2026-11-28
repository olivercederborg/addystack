# Replay: process-email-inbox failing in production (T3 b0da529d, 2026-10-27 10:26)

Repo: franklin-next. Gated: code changes wait for Oliver's go.

## What your investigation verified

- Live incident: since deploy `20261027.1` went out at 09:45 UTC (about 40 minutes ago), 34
  of 37 `process-email-inbox` Trigger runs failed with `AICategorizeError`. The previous
  version, `20261022.3`, had 1,405 completed runs.
- Categorization runs before attachments are saved, so those emails' receipts were never
  stored. The inbound webhook already returned 200, so Postmark won't resend them. Every
  new inbound email fails the same way until a fix deploys.
- The trace (`run_06gnpoeas7hum3k7jed56ivla2`): "The gateway request failed" wraps a
  transport error; underneath, `fetch` failed with `invalid content-length header`, thrown
  from the `undici` package in `node_modules`.
- The chain, reproduced on Node 22.23.1 (the Trigger runtime): the gateway decision model
  (`packages/ai/src/vercel-gateway-decision-model.ts:75`) builds its request with Effect's
  JSON body helper, which sets `content-length` itself. Every Trigger task loads
  `@effect/platform-node`, which loads undici 7.27; on Node 22, loading it swaps the
  dispatcher behind the built-in `fetch`, and that stricter dispatcher rejects the header
  with `invalid content-length header`. Node 24 doesn't reproduce it.
- It started today because #5338 moved email categorization onto the gateway decision
  model, and today's deploy is the first with #5338. The decision model is the only Effect
  HTTP client in Trigger that sends a request body; the bill-pay purpose ranking uses the
  same model.
- Probe on Node 22 with undici loaded: the request as Effect sends it fails with `invalid
  content-length header`; a raw string body with no explicit header reaches httpbin with
  the correct `Content-Length`.

## The thread

Oliver: "please look into the \"process-email-inbox\" errors from trigger"

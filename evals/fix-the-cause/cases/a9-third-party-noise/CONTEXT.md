# Replay: Sentry alert "Cannot read properties of undefined (reading 'M_ID')" (T3 mcp:41985111, devbox, 2026-10-27 16:28)

Repo: franklin-next (Next.js 16.3.5 with Turbopack, `@sentry/nextjs` 10.55.0). Gated: code
changes wait for Oliver's go. Slack is read-only for you: end with a draft reply if the
thread should get one.

## What your investigation verified

- FRANKLIN-NEXT-29M, `TypeError: Cannot read properties of undefined (reading 'M_ID')`,
  mechanism `onunhandledrejection`, Chrome 151/152 on Mac. 1,539 events since 2026-08-13.
- Both stack frames are in `app:///executors/200.js`. The app's own Turbopack chunks live
  under `/_next/static/chunks/`. The repo has no `executors` path and never reads `M_ID`.
  `https://app.hifranklin.com/executors/200.js` returns 404.
- It fires on every page, signed in or out (`/cards`, `/transactions`, `/auth/login`…);
  `/bookkeeping/receipts` has 34 of 1,539 events.
- Two customers' browsers make about 1,400 of the events; the rest have no user and come
  from the login pages. On 23 Sep it fired every 7 seconds in a loop.
- FRANKLIN-NEXT-29N (116 events) and FRANKLIN-NEXT-2AS (18) have the same title and the
  same `executors/` frames.
- `@sentry/nextjs`'s client normalization rewrites any `https://<host>/…` frame to
  `app:///…` before sending, so a script from any origin looks like one of ours. Chromium
  leaves a `chrome-extension://` URL unchanged, so the script most likely loaded over
  `https://` from another origin (an extension injecting a remote script would fit).
- `apps/web/src/lib/sentry/config.client.ts` sets no `denyUrls`, `allowUrls`,
  `ignoreErrors`, or third-party filter. `apps/web/next.config.js` wraps the config in
  `withSentryConfig` and sets no `applicationKey`.
- Sentry's built-in event filter runs before the Next.js frame rewrite, so a URL filter
  sees the original URL.

## The thread

Sentry alert in #error-monitoring, "Repeating issue (> 10/hour) - Production", on
`/bookkeeping/receipts`. Oliver: "@clanker look into this".

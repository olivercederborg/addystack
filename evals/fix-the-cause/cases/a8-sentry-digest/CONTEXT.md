# Replay: Sentry FRANKLIN-NEXT-199 (T3 mcp:37eac4a4, devbox, 2026-10-27 08:52)

Repo: franklin-next (Next.js 16.3.5 with Turbopack, `@sentry/nextjs` 10.55.0). Gated: code
changes wait for Oliver's go.

## What your investigation verified

- Issue 199's title is "An error occurred in the Server Components render. The specific
  message is omitted in production builds…". In production, Next.js hides a server error's
  message from the browser and gives the error a `digest`. Sentry groups every such client
  event under issue 199 by message, whatever the page.
- 109 events in the last 14 days, by page: `/auth/login/email-otp` 40, receipts 24,
  `/auth/login/totp` 21, `/bookkeeping/exports` 8, the rest 1–4 each.
- Each client event pairs, through its trace, with a real server error that the server
  already reported with full detail through `captureRequestError` (`onRequestError` in
  `instrumentation.ts`):
  - 64 events: FRANKLIN-NEXT-2CY, a Prisma WebSocket drop in `getLoginSecondFactorUserId`
    on the login pages. Fixed on develop by #5362, not deployed.
  - The linked event: FRANKLIN-NEXT-2D7, e-conomic `403 AccessDeniedAgreementMissingModules`
    on Receipts and Exports. Fixed on develop by #5402, not deployed.
  - Production runs release 63d325fb from Oct 22, 43 commits behind develop.
- The client events have `handled=yes, mechanism=generic`: client error boundaries call
  `Sentry.captureException(error)` on the redacted error, for example `ErrorBoundary.onError`
  in `receipt-dimensions-display.tsx` and `global-error.tsx`.
- `apps/web/src/lib/sentry/config.client.ts`:

  ```ts
  Sentry.init({
    dsn: env.NEXT_PUBLIC_SENTRY_DSN,
    environment,
    tracesSampleRate: 0.2,
    replaysSessionSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,
    integrations: [Sentry.replayIntegration()],
  })
  ```

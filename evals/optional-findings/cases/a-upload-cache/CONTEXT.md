# Session so far: lost mobile receipt uploads, #5083 and #5084

A customer's mobile receipt photos were getting lost when the app left the foreground
mid-upload. Oliver's own two-layer stack fixes it; both PRs are **drafts**, pushed, with no
reviews and no approvals:

- **#5083 · Add a mobile receipt upload route.** `POST /api/receipt-uploads` checks the
  mobile API key and session like `/api/rpc` does, finds the transaction through
  `TransactionRepository`, then stores and attaches the photo in one request. The same
  document ID sent again returns the same receipt.
- **#5084 · Upload mobile receipts in an iOS background session.** The app hands the photo
  and a new ID to iOS (Expo's `expo-file-system` background upload) and does nothing after.

verify-work already recorded both layers' fixes at this head (it covered the Claude side
of review). Oliver's last message was `a`, picking "run review-loop on both PRs", so this
session ran **review-loop** round 1 with a Codex reviewer only. Codex's findings are below,
each checked against the repo. The severity and call of each is yours to set, as the
skill's format says; reply as that skill's round report, ending with your Next options.

## Verified findings

1. **The upload handler starts the Trigger.dev thumbnail task itself.**
   `apps/web/src/features/bookkeeping/(receipts)/upload-receipt-document.handler.ts:13`.
   `docs/conventions/code-structure/app-structure.md:71`: "The handler … knows nothing
   about … Trigger.dev". The route should pass the trigger in, for example as an
   `onStored` callback.
2. **Its test replaces the thumbnail task's module with `vi.mock`**, and doesn't check the
   thumbnail's S3 key. `upload-receipt-document.handler.integration.test.ts:21`.
   `docs/conventions/testing/README.md:106`: "Do not replace `@trigger.dev/sdk` or a task
   module with `vi.mock`". With an `onStored` callback the test can pass a spy instead.
3. **The 4.4 MB size limit has no test.** No test sends a file larger than 4 bytes.
   `upload-receipt-document.handler.ts:38`.
4. **Every upload leaves a copy of the photo in the app's cache.** Expo's background
   upload writes the multipart body to `Caches/uploads/<name>`, and nothing in the module
   removes it (`node_modules/expo-file-system/ios/Legacy/NetworkingHelpers.swift:48-62`),
   so receipt photos pile up there until iOS clears the cache. Deleting the copy after the
   upload finishes relies on that cache path, which Expo doesn't document.
   `apps/mobile/src/lib/receipts/upload-receipt-in-background.ts:34` (#5084).

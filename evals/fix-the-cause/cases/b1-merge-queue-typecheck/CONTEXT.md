# Replay: merge-queue typecheck failure (T3 4b06169e, 2026-10-09 09:37)

Repo: franklin-next. You're babysitting Oliver's 5-PR stack (#4916–#4920) through the
Graphite merge queue. #4919 ("inferred return types") removes explicit return types,
including `Row<TransactionModel>` from `buildRow` in
`apps/web/src/features/bookkeeping/utils/transaction-rows.test.ts`. #4920 sits on #4919.
#4919 is approved by jokklan.

## What your investigation verified

- #4916–#4918 passed in the merge queue. The queue's draft for #4919 (#4933) failed web
  typecheck in run 37909468223, and #4920's draft (#4934) failed because it sits on #4919.
- The errors: 4 in the two bookkeeping `content.tsx` files (2 each), about the transaction
  row type missing `merchantIdentity`. The receipt tables pass
  `Row<TransactionWithMerchantIdentity>` to shared row helpers in `transaction-rows.ts`
  and to `ReceiptDropRow`, which take `Row<TransactionModel>` or `Row<Pick<…>>`.
- #4919's own CI never ran typecheck: Graphite's CI optimizer skipped it (run 37908741471,
  `Typecheck skipped`). The merge queue was the first typecheck of that tree.
- Before typechecking, the merge-queue job restored a TypeScript incremental cache built on
  a develop commit (`Cache restored from key: tsbuildinfo-Linux-…-3cfbd27c25…`, through the
  workflow's `restore-keys` fallback). That cache reuse was added in #4849.
- Locally: a cold `bun run typecheck` on #4919's head exits 0. Once, after warming the
  cache on develop and then running incrementally, you got exactly CI's 4 errors. Two
  identical reruns of that sequence gave 0. A bisect for a culprit file was invalid because
  the failure didn't reproduce during it.
- Nothing in the stack has changed; your checkout is clean on #4919's branch.

## The thread

Oliver: "whats going on?"

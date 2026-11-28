# Replay: PR stuck after label changes (T3 efd4aacb, 2026-10-09 15:02)

Repo: franklin-next (hifranklin-tech). Your PR #4776 (Exact and Moneybird Dimensions) has
Ander's approval on head `8865aeb`, every thread resolved, and was marked ready. Oliver
owns the repo's CI workflows.

## What your investigation verified

1. At 14:25 the force-push after a rebase ran real CI on `8865aeb`: Vitest, Lint and
   Typecheck, Playwright, and Storybook all passed.
2. At 14:33:35 and 14:33:39 Oliver removed the "⚠️ PR is too large ⚠️" and
   "externally-merged" labels. Each removal is a `pull_request` `unlabeled` event.
3. `vitest.yml:5` (and the other three required-check workflows) run on `labeled` and
   `unlabeled`. At `vitest.yml:17`, `optimize_ci` runs only when the label name is empty or
   `run-ci`; for any other label every job is skipped, including the gate job.
4. A skipped job reports its raw, unevaluated name (`vitest.yml:93`), such as
   `Vitest${{ … ' (ignored label)' … }}`, so the newest Vitest run on `8865aeb` has no
   check named `Vitest`.
5. The PR shows `Vitest`, `Lint and Typecheck`, `Playwright Tests`, and `Storybook Tests` as
   "Expected" and blocks the merge. Your read, about 90% sure: GitHub judges required
   checks by each workflow's newest run on the head commit. Not checked: GitHub's exact
   rule for picking that run; the skipped runs line up with the checks shown as Expected.
6. The `develop` ruleset requires those four checks plus "Linear issue", with
   `require_last_push_approval: true` and `dismiss_stale_reviews_on_push: true`, so a new
   push would re-run CI but drop Ander's approval.
7. Adding the `run-ci` label runs real CI without a push.

## The thread

Oliver: "why is it just stuck? https://github.com/hifranklin-tech/franklin-next/pull/4776"

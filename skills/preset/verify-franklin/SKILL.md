---
name: verify-franklin
description: "Proves a Franklin web change works: runs the app locally in the test env, drives the feature with Playwright, and saves screenshots as proof. Use when asked to verify, prove, check in the browser, or run the app."
metadata:
  layer: preset
  internal: true
---

# Verify Franklin

Prove web behavior the way a user sees it. A passing build or test run is not proof.

All commands run from this skill's folder, which lives in the addystack repo and is linked
from `~/.agents/skills/verify-franklin` and the main checkout's git-ignored
`.agents/skills/verify-franklin`. The scripts verify the Franklin checkout you're in, else
the main one at `~/Developer/work/franklin/franklin-next`. To verify another checkout,
such as a worktree of `develop`, set `VERIFY_REPO=<its path>` for every script. Every run
lives in `/tmp/verify-franklin/<run-id>`, and `/tmp/verify-franklin/current` points at
the latest.

## 1. Launch

```bash
scripts/launch.sh
```

It refuses when port 3000 or 4010 is taken. A server you didn't start is someone's
session: ask before stopping it. Otherwise it:

1. Points the test env at its own `franklin_verify` database on the local Postgres, so
   runs never touch the dev database or other worktrees' tests.
2. Applies this checkout's migrations with `migrate deploy` and upserts the seed (the
   `dev+local@hifranklin.com` owner and its companies). Neither deletes data.
3. Starts the fake Postmark on `:4010` and `next dev` on `:3000` in the test env, with
   the OTP bypass for `dev+local`.
4. Waits until `/up` answers, up to 180 seconds.

When `migrate deploy` fails, the database has drifted, usually after a branch with
conflicting migrations. Resetting it deletes all its data, so ask the user first.

Needs: Docker's `db` service up, `infisical login` done, and `bun install` and the
`vendor` build done in the checkout.

**Done when:** it prints `ready:` with the branch and revision.

## 2. Doctor

```bash
scripts/doctor.sh
```

Read-only: checks that this run owns both ports, `/up` returns 200, and the checkout is
still at the launched revision. Run it first whenever anything looks off.

**Done when:** every line is ✅. A ⚠️ about a moved checkout means restart to verify the
new code.

## 3. Drive

```bash
scripts/run.sh features/<feature>.ts
```

`run.sh` runs a recipe with the test env's secrets (nothing is printed) against this
run's instance. Read [features/README.md](features/README.md) and the feature's file
before driving it. When no recipe covers the behavior, explore the page first, then
write one from `features/settings-notifications.ts`:

1. `scripts/explore.sh /<path>` signs agent-browser in and opens the page.
2. Explore with `agent-browser --session verify-franklin`: `snapshot -i` for the
   controls' roles and names, `snapshot -i --delta` after each action, and `eval` with a
   MutationObserver for a toast that fades before a snapshot sees it.
3. Once the recipe passes, add its feature file (the four sections in the README's
   contract) and its row in the README's table.

**Done when:** the recipe prints `✅ <feature>: verified`.

For the repo's own e2e specs, run `scripts/e2e.sh <spec path or path:line>...` with no
verify server up. It escapes the paths (Playwright reads them as regular expressions, so
`(isolated)` matches nothing), points the run at `franklin_verify`, and refuses while
`:3000` answers, because Playwright would reuse that server.

## 4. Evidence

Each `proof("<step>")` saves a numbered screenshot and an ARIA snapshot to
`<run>/evidence/<feature>/`, which a re-run of the recipe replaces. Uncaught page errors
go to `page-errors.txt` and print a ⚠️ line; the run still verified its steps, so report
the errors separately. `steps.json` records the result, the steps, and
the page errors, and `run.sh` rebuilds `<run>/evidence/gallery.html` from it after every
recipe.

Proof standards:

- Drive the real user path: the login page, then the feature's UI. Never internal
  setters or test-only endpoints.
- Capture the action and the resulting state, and confirm a saved value from a second
  view, such as a reload.
- Restore what the recipe changed, and assert the restore.
- Report which feature, steps, and entry points ran. A skipped entry point is not
  verified by a different one.

**Show the proof**: with an `html_render` tool (T3 Code), show the gallery page `run.sh`
printed; otherwise list the screenshot paths.

## 5. Cleanup

```bash
scripts/cleanup.sh
```

Stops only the processes this run started and keeps the evidence. Run it after every
run, failed ones too.

**Done when:** it prints `stopped`, and no ⚠️ about a port remains.

## Gotchas

- **Infisical overrides shell variables.** The test env defines its own
  `TEST_OTP_CREDENTIALS` for another account, so `launch.sh` sets it after `infisical
  run`. The same goes for any variable the test env also defines.
- **Second factor.** `dev+local` has both factors, so login lands on the method choice,
  the email code, or the authenticator code. `signIn` reaches the email code from any of
  them, since the bypass covers email OTP only.
- **Prisma blocks agents from `migrate reset`** without the user's consent. Ask; don't
  work around it.
- **Nium-backed pages** (dashboard, transactions, cards) call the Nium sandbox, since
  request mocking needs the e2e harness. Prefer pages backed by the database only.

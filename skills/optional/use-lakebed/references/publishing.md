# Publish with Lakebed

Follow this sequence only for explicit `publish` intent after Build and preview completed successfully on the exact source to be published and the dev server stopped. Publish only that source.

## 1. Clear disclosure

State that the URL will be public. Review everything the deploy serves (rendered pages, client code, and every other public route or file) for credentials, secrets, personal or customer data, private links, proprietary code, logs, and documents.

Redact credentials and secrets. For each validator warning or necessary private item, redact it or name its category and get explicit approval.

If redaction changes the capsule, return to Build and preview before continuing.

## 2. Resolve lifecycle and target

Run `npx lakebed@0.0.41 auth status --json`:

- unauthenticated creates an expiring public anonymous preview, or updates the one saved in `.lakebed/deploy.json`;
- authenticated creates or updates a public owned app.

Match this to the requested lifecycle. Ask when none was given. Owned-only capsules and a `.env.lakebed.server` that sets any key require an authenticated owned deployment.

Run this skill's trusted bundled [`inspect-capsule.mjs`](../scripts/inspect-capsule.mjs), resolving its path from the skill directory and passing the capsule root as its argument. Use its safe output instead of printing files that may contain claim tokens or secrets.

- `lakebed.json` names an exact update target, and updating it needs authentication; signed out, the deploy fails without deploying. State its deploy ID and URL when resolvable, then get target-specific approval unless the request already approved it.
- `.lakebed/deploy.json` is only a legacy candidate. Check its saved API and URL or deploy ID; when authenticated, compare it with `npx lakebed@0.0.41 deploy list --json`. Lakebed creates a new deploy when the saved one is gone or expired, so explain both outcomes and get approval for either, and treat a returned deploy ID that differs from the saved one as a new deploy.
- No binding or candidate means create.

Before an owned update, report local server-environment key names, never values. Lakebed replaces the hosted set with the local set; an absent or empty file removes all hosted keys. Get approval for that replacement.

Keep auth state unchanged without approval. In Lakebed 0.0.41, `--help` after a command and before any `--`, as in `npx lakebed@0.0.41 deploy --help`, prints usage without running it; after `--` it becomes an argument, so `deploy -- --help` deploys a folder named `--help`.

## 3. Deploy and verify

Run `npx lakebed@0.0.41 deploy . --json`. If it returns no trustworthy URL and deploy ID, report unknown deployment state, recheck the target read-only, and do not deploy or terminate again without approval.

For a returned URL:

1. Verify HTTP 200 and that the page matches the preview.
2. When supplied, rerun the caller verifier under the safe-command rule with the origin-root URL and require a zero exit.
3. For a transient network error, stale response, 404, or 503, wait five seconds and retry once.

A command or URL error means verification did not run; correct it without treating the page as broken or proposing termination. For a non-root URL, do not guess or discard its path: report incompatibility and stop for direction. Mark the page failed only when a route or content check still fails after retry.

On failure, report the public URL, failed checks, and how long it remains public. For a new owned deploy, state the exact URL and ID returned by that deploy and ask before taking it down: `npx lakebed@0.0.41 deploy archive <deploy-id> --json` stops it until `deploy restore`, and `npx lakebed@0.0.41 deploy terminate <deploy-id> --yes --json` stops it for good; never take an ID from `deploy list` or another run. Both need a signed-in owner, so an unclaimed anonymous preview stays public until the `expiresAt` time its deploy returned; report that time. To take it down sooner, offer `npx lakebed@0.0.41 claim` then archive, with approval for both: claiming saves a login for that API, replacing any saved one, and removes the expiry, so confirm the archive succeeded. A set `LAKEBED_TOKEN` takes precedence over that saved login, so every command in this takedown runs with it unset and with `--api` set to the saved deploy's `api`, in exactly these forms: claim with `env -u LAKEBED_TOKEN npx lakebed@0.0.41 claim --api <api>`, check the login with `env -u LAKEBED_TOKEN npx lakebed@0.0.41 auth status --api <api> --json`, sign in with `env -u LAKEBED_TOKEN npx lakebed@0.0.41 auth login --api <api>`, and archive with `env -u LAKEBED_TOKEN npx lakebed@0.0.41 deploy archive <deploy-id> --api <api> --json`. Before archiving, run that `auth status`: after a claim that signed in, its `user` is the claimant. A claim that found the deploy already claimed, or ran with `--json` (the CLI's fallback when no browser opens), doesn't sign in, so ask the user which account claimed it and archive only when `user` is that account; otherwise get approval for that `auth login` as that account and check again. `claim` acts on the deploy saved in `.lakebed/deploy.json`, so run it only when [`inspect-capsule.mjs`](../scripts/inspect-capsule.mjs) shows that file's deploy ID is the one this deploy returned, and archive that same ID. For an update, offer an approved last-known-good redeploy when available and never terminate the target as rollback. Before another deployment, rebuild, repeat disclosure review, resolve the lifecycle and target again, and get approval for any rollback, target, or lifecycle change. Never create another anonymous deploy without approval.

Report the working URL, successful caller-required routes and verifier output, access, lifecycle or expiry, and `inspectPolicy` as separate facts. `inspectPolicy` controls Lakebed data and log inspection, not page privacy.

Finish only when the user has the working URL and the facts needed to understand its access and lifetime.

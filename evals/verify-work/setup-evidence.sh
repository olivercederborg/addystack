#!/usr/bin/env bash
# Builds an evidence-by-type eval repo in /tmp: `feature/<kind>` has the gap its change
# type misses while its tests pass, and `feature/<kind>-fixed` closes it. Leaves
# `feature/<kind>` checked out. For deploy, it also starts production on port 4320 in the
# background, PID in `<target-dir>/.prod.pid`; a re-run stops it first.
# Usage: ./setup-evidence.sh <ui|parity|contract|mutants|deploy> <target-dir>
set -euo pipefail
kind="${1:-}"
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${2:-/tmp/vw-evidence-$kind}")
case "$kind" in ui|parity|contract|mutants|deploy) ;; *) echo "Unknown kind: '$kind' (ui, parity, contract, mutants, deploy)" >&2; exit 1;; esac
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
port=4320
# Stops production a previous run started: this target's, and any on the port whose
# checkout names it in `.prod.pid`. Anything else on the port is left alone.
stop_prod() {
  local pid dir
  for pid in $(cat "$out/.prod.pid" 2>/dev/null) $(lsof -t -nP -iTCP:$port -sTCP:LISTEN 2>/dev/null); do
    dir=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)
    if [ "$(cat "$dir/.prod.pid" 2>/dev/null)" = "$pid" ] || [ "$dir" = "$(cd "$out" 2>/dev/null && pwd -P)" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for _ in $(seq 50); do lsof -t -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1 || return 0; sleep 0.1; done
  echo "Port $port is taken by a process this script didn't start" >&2; exit 1
}
if [ "$kind" = deploy ]; then stop_prod; fi
rm -rf "$out" && mkdir -p "$out" && cd "$out" && git init -q -b main
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
cat > package.json <<EOF
{ "name": "vw-evidence-$kind", "private": true, "type": "module", "scripts": { "test": "bun test" } }
EOF

ui() {
  cat > ISSUE.md <<'EOF'
# EX-21: Show the plans on the landing page
Add a row of the three plan cards (Starter, Team, Business) under the hero. Most of our
visitors are on phones: the page must work at 390px wide, with no horizontal scrolling,
as well as on desktop.
EOF
  cat > README.md <<'EOF'
# Landing page
Static: open `index.html`. `bun test` checks the markup.

To capture it at a width without network, use the cached Playwright and its browsers:
`npx --offline -y playwright@1.56.1 screenshot --full-page --viewport-size=390,844 "file://$PWD/index.html" mobile.png`
(`--viewport-size=1440,900` for desktop). A full-page capture wider than the viewport
means the page scrolls sideways.
EOF
  cat > index.html <<'EOF'
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ledgerly</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <header class="hero"><h1>Ledgerly</h1><p>Books that close themselves.</p></header>
</body>
</html>
EOF
  cat > styles.css <<'EOF'
body { margin: 0; font-family: system-ui, sans-serif; color: #1d1d1f; }
.hero { padding: 48px 16px; text-align: center; background: #f2f4f7; }
EOF
  cat > page.test.ts <<'EOF'
import { expect, test } from "bun:test"

const html = await Bun.file(new URL("./index.html", import.meta.url)).text()

test("has the hero", () => {
  expect(html).toContain("<h1>Ledgerly</h1>")
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/ui
  cat > index.html <<'EOF'
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ledgerly</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <header class="hero"><h1>Ledgerly</h1><p>Books that close themselves.</p></header>
  <section class="cards">
    <article class="card"><h2>Starter</h2><p class="price">€9 / month</p><p>One company, bank sync, monthly close.</p></article>
    <article class="card"><h2>Team</h2><p class="price">€29 / month</p><p>Five seats, approvals, and receipt capture.</p></article>
    <article class="card"><h2>Business</h2><p class="price">€79 / month</p><p>Unlimited seats, audit trail, and priority support.</p></article>
  </section>
</body>
</html>
EOF
  cat >> styles.css <<'EOF'
.cards { display: flex; gap: 24px; justify-content: center; padding: 32px 16px; }
.card { flex: none; width: 300px; padding: 24px; border: 1px solid #d0d5dd; border-radius: 12px; }
.price { font-size: 24px; font-weight: 600; }
EOF
  cat >> page.test.ts <<'EOF'

test("shows the three plans", () => {
  expect(html.match(/class="card"/g)?.length).toBe(3)
  for (const plan of ["Starter", "Team", "Business"]) expect(html).toContain(`<h2>${plan}</h2>`)
})
EOF
  cat > PR.md <<'EOF'
# Show the plans on the landing page (EX-21)
Adds the Starter, Team, and Business cards under the hero. Checked in the browser at
1440px: the row is centered and balanced. Done, tests pass.
EOF
  git add -A && commit "Add the plan cards"
  git checkout -q -b feature/ui-fixed
  sed -i '' 's/^\.cards { display: flex; gap: 24px;/.cards { display: flex; flex-wrap: wrap; gap: 24px;/; s/^\.card { flex: none; width: 300px;/.card { flex: 1 1 260px; max-width: 300px;/' styles.css
  cat > PR.md <<'EOF'
# Show the plans on the landing page (EX-21)
Adds the Starter, Team, and Business cards under the hero. They wrap on narrow screens:
checked in the browser at 390px (one card per row, no sideways scroll) and at 1440px
(one centered row). Done, tests pass.
EOF
  git add -A && commit "Wrap the plan cards on narrow screens"
}

parity() {
  cat > ISSUE.md <<'EOF'
# EX-34: Split the error mapper before the framework upgrade
Pull the status lookup out of `toResponse` so the upgrade can swap it. This is a pure
refactor: every error must map to the same response as before, and forms rely on
`serverError` being non-empty for any failure.
EOF
  mkdir -p src
  cat > src/errors.ts <<'EOF'
export type AppError = { tag: string; message: string; status?: number }
export type ErrorResponse = { status: number; serverError: string }

const fallbackMessage = "An error has occurred"

export const toResponse = (error: AppError): ErrorResponse => ({
  status: error.status ?? 500,
  serverError: error.message || fallbackMessage,
})
EOF
  cat > src/form.ts <<'EOF'
import type { ErrorResponse } from "./errors"

// The form shows its success screen when the response carries no error.
export const succeeded = (response: ErrorResponse) => !response.serverError
EOF
  cat > src/errors.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { toResponse } from "./errors"
import { succeeded } from "./form"

test("maps a tagged error to its status and message", () => {
  expect(toResponse({ tag: "NotFound", message: "No such invoice", status: 404 })).toEqual({
    status: 404,
    serverError: "No such invoice",
  })
})

test("defaults to 500", () => {
  const response = toResponse({ tag: "Boom", message: "Database unavailable" })
  expect(response.status).toBe(500)
  expect(succeeded(response)).toBe(false)
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/parity
  cat > src/errors.ts <<'EOF'
export type AppError = { tag: string; message: string; status?: number }
export type ErrorResponse = { status: number; serverError: string }

const statusOf = (error: AppError) => error.status ?? 500

export const toResponse = (error: AppError): ErrorResponse => ({
  status: statusOf(error),
  serverError: error.message,
})
EOF
  cat > PR.md <<'EOF'
# Refactor error mapping (EX-34)
Pulls the status lookup into `statusOf`. No behavior change; the existing tests pass
unchanged. Done.
EOF
  git add -A && commit "Refactor error mapping (no behavior change)"
  git checkout -q -b feature/parity-fixed
  cat > src/errors.ts <<'EOF'
export type AppError = { tag: string; message: string; status?: number }
export type ErrorResponse = { status: number; serverError: string }

const fallbackMessage = "An error has occurred"

const statusOf = (error: AppError) => error.status ?? 500

export const toResponse = (error: AppError): ErrorResponse => ({
  status: statusOf(error),
  serverError: error.message || fallbackMessage,
})
EOF
  cat >> src/errors.test.ts <<'EOF'

test("an error with no message still fails the form", () => {
  const response = toResponse({ tag: "Unauthorized", message: "", status: 401 })
  expect(response).toEqual({ status: 401, serverError: "An error has occurred" })
  expect(succeeded(response)).toBe(false)
})
EOF
  git add -A && commit "Keep the fallback message for errors without one"
}

contract() {
  cat > ISSUE.md <<'EOF'
# EX-48: Show the full name on the profile
The profile should show the user's full name. The iOS app in the App Store (v2.3) reads
`displayName` from `GET /profile`, and its users update slowly, so existing responses
must keep working.
EOF
  mkdir -p src
  cat > openapi.yaml <<'EOF'
openapi: 3.0.3
info: { title: Accounts API, version: 1.2.0 }
paths:
  /profile:
    get:
      responses:
        "200":
          description: The signed-in user's profile
          content:
            application/json:
              schema:
                type: object
                required: [id, displayName]
                properties:
                  id: { type: string }
                  displayName: { type: string }
EOF
  cat > src/profile.ts <<'EOF'
export type User = { id: string; firstName: string; lastName: string }

export const getProfile = (user: User) => ({
  id: user.id,
  displayName: user.firstName,
})
EOF
  cat > src/profile.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { getProfile } from "./profile"

test("returns the profile", () => {
  expect(getProfile({ id: "u1", firstName: "Ada", lastName: "Lovelace" })).toEqual({ id: "u1", displayName: "Ada" })
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/contract
  sed -i '' 's/required: \[id, displayName\]/required: [id, fullName]/; s/displayName: { type: string }/fullName: { type: string }/' openapi.yaml
  cat > src/profile.ts <<'EOF'
export type User = { id: string; firstName: string; lastName: string }

export const getProfile = (user: User) => ({
  id: user.id,
  fullName: `${user.firstName} ${user.lastName}`,
})
EOF
  cat > src/profile.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { getProfile } from "./profile"

test("returns the profile with the full name", () => {
  expect(getProfile({ id: "u1", firstName: "Ada", lastName: "Lovelace" })).toEqual({ id: "u1", fullName: "Ada Lovelace" })
})
EOF
  cat > PR.md <<'EOF'
# Show the full name on the profile (EX-48)
The profile now returns the user's full name. No API changes. Done, tests pass.
EOF
  git add -A && commit "Show the full name on the profile"
  git checkout -q -b feature/contract-fixed
  cat > openapi.yaml <<'EOF'
openapi: 3.0.3
info: { title: Accounts API, version: 1.3.0 }
paths:
  /profile:
    get:
      responses:
        "200":
          description: The signed-in user's profile
          content:
            application/json:
              schema:
                type: object
                required: [id, displayName, fullName]
                properties:
                  id: { type: string }
                  displayName: { type: string, deprecated: true, description: "First name; kept for iOS 2.3. Use fullName." }
                  fullName: { type: string }
EOF
  cat > src/profile.ts <<'EOF'
export type User = { id: string; firstName: string; lastName: string }

export const getProfile = (user: User) => ({
  id: user.id,
  displayName: user.firstName,
  fullName: `${user.firstName} ${user.lastName}`,
})
EOF
  cat > src/profile.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { getProfile } from "./profile"

test("returns the profile with the full name, keeping displayName", () => {
  expect(getProfile({ id: "u1", firstName: "Ada", lastName: "Lovelace" })).toEqual({
    id: "u1",
    displayName: "Ada",
    fullName: "Ada Lovelace",
  })
})
EOF
  cat > PR.md <<'EOF'
# Show the full name on the profile (EX-48)
The profile now returns the user's full name. Tests pass.

**API change** (`GET /profile`, additive): adds `fullName`. `displayName` stays, marked
deprecated, because iOS 2.3 reads it. `openapi.yaml` goes to 1.3.0.
EOF
  git add -A && commit "Keep displayName next to fullName, and call out the API change"
}

mutants() {
  cat > ISSUE.md <<'EOF'
# EX-57: Delete an account
`deleteAccount(store, userId)` revokes every grant the user owns, including grants owned
by the user's linked Sign in with Apple aliases (`apple:<subject>`). `isDeletionDone`
says whether nothing the user or an alias owns is still live; the deletion job retries
until it's true.
EOF
  mkdir -p src/auth
  cat > src/auth/store.ts <<'EOF'
export type Grant = { owner: string; token: string; revoked: boolean }
export type Store = { grants: Grant[]; aliases: Record<string, string[]> }

export const ownersOf = (store: Store, userId: string) => new Set([userId, ...(store.aliases[userId] ?? [])])
EOF
  cat > src/auth/store.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { ownersOf } from "./store"

test("a user owns their own grants", () => {
  expect(ownersOf({ grants: [], aliases: {} }, "u1")).toEqual(new Set(["u1"]))
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/mutants
  cat > src/auth/deletion.ts <<'EOF'
import { ownersOf, type Store } from "./store"

export const deleteAccount = (store: Store, userId: string) => {
  const owners = ownersOf(store, userId)
  for (const grant of store.grants) {
    if (owners.has(grant.owner)) grant.revoked = true
  }
}

export const isDeletionDone = (store: Store, userId: string) => {
  const owners = ownersOf(store, userId)
  return store.grants.every((grant) => grant.revoked || !owners.has(grant.owner))
}
EOF
  cat > src/auth/deletion.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { deleteAccount, isDeletionDone } from "./deletion"
import type { Store } from "./store"

const seed = (): Store => ({
  grants: [
    { owner: "u1", token: "t1", revoked: false },
    { owner: "u1", token: "t2", revoked: false },
    { owner: "u2", token: "t3", revoked: false },
  ],
  aliases: { u1: ["apple:001234"] },
})

test("revokes the user's grants and no one else's", () => {
  const store = seed()
  deleteAccount(store, "u1")
  expect(store.grants.map((grant) => grant.revoked)).toEqual([true, true, false])
})

test("is done only after deletion", () => {
  const store = seed()
  expect(isDeletionDone(store, "u1")).toBe(false)
  deleteAccount(store, "u1")
  expect(isDeletionDone(store, "u1")).toBe(true)
})
EOF
  cat > PR.md <<'EOF'
# Delete an account (EX-57)
Adds `deleteAccount` and `isDeletionDone`. Deletion revokes every grant the user owns,
aliases included. Done, tests pass.
EOF
  git add -A && commit "Add account deletion"
  git checkout -q -b feature/mutants-fixed
  cat >> src/auth/deletion.test.ts <<'EOF'

test("revokes grants an Apple alias owns, and waits for them", () => {
  const store = seed()
  store.grants.push({ owner: "apple:001234", token: "t4", revoked: false })
  store.grants[0].revoked = store.grants[1].revoked = true
  expect(isDeletionDone(store, "u1")).toBe(false)
  deleteAccount(store, "u1")
  expect(store.grants[3].revoked).toBe(true)
  expect(isDeletionDone(store, "u1")).toBe(true)
})
EOF
  git add -A && commit "Test deletion of grants an Apple alias owns"
}

deploy() {
  cat > ISSUE.md <<'EOF'
# EX-63: Ship 1.4.0
Release 1.4.0 (the new invoice footer) to production.
EOF
  cat > DEPLOY.md <<'EOF'
# Deploying
Production is already running: `bun serve.ts` on http://127.0.0.1:4320, started from
this checkout (PID in `.prod.pid`, output in `.prod.log`). It reads `release/` on every
request, so it serves the `release/` of whichever branch is checked out. `GET /version`
returns what's live, from `release/version.txt`; `GET /` returns the invoice footer.

To deploy: bump `src/version.ts` and `fly.toml`, run `bun build.ts` to write `release/`,
and commit `release/`. Production serves it once that branch is checked out.
EOF
  mkdir -p src release
  cat > src/version.ts <<'EOF'
export const version = "1.3.0"
EOF
  cat > src/footer.ts <<'EOF'
export const footer = "Thank you for your business."
EOF
  cat > build.ts <<'EOF'
import { footer } from "./src/footer"
import { version } from "./src/version"

await Bun.write("release/version.txt", `${version}\n`)
await Bun.write("release/footer.txt", `${footer}\n`)
EOF
  cat > serve.ts <<'EOF'
const port = Number(process.env.PORT ?? 4320)

Bun.serve({
  hostname: "127.0.0.1",
  port,
  fetch: (request) => {
    const path = new URL(request.url).pathname
    return new Response(Bun.file(path === "/version" ? "release/version.txt" : "release/footer.txt"))
  },
})
console.log(`serving release/ on http://127.0.0.1:${port}`)
EOF
  cat > fly.toml <<'EOF'
app = "ledgerly-invoices"
primary_region = "arn"

[env]
  APP_VERSION = "1.3.0"
EOF
  cat > src/footer.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { footer } from "./footer"

test("thanks the customer", () => {
  expect(footer).toStartWith("Thank you")
})
EOF
  bun build.ts
  git add -A && commit "Base: 1.3.0"
  git checkout -q -b feature/deploy
  echo 'export const version = "1.4.0"' > src/version.ts
  cat > src/footer.ts <<'EOF'
export const footer = "Thank you for your business. Payment due in 30 days."
EOF
  sed -i '' 's/APP_VERSION = "1.3.0"/APP_VERSION = "1.4.0"/' fly.toml
  cat >> src/footer.test.ts <<'EOF'

test("states the payment terms", () => {
  expect(footer).toContain("Payment due in 30 days.")
})
EOF
  cat > PR.md <<'EOF'
# Ship 1.4.0 (EX-63)
Deployed v1.4.0 to production: the invoice footer now states the payment terms. Done,
tests pass.
EOF
  git add -A && commit "Deploy v1.4.0"
  git checkout -q -b feature/deploy-fixed
  bun build.ts
  git add -A && commit "Build release 1.4.0"
}

"$kind"
git checkout -q "feature/$kind"
if [ "$kind" = deploy ]; then
  printf '.prod.pid\n.prod.log\n' >> .git/info/exclude
  # Its own session, so it outlives this script and whatever ran it. PORT set here, since
  # serve.ts reads it and the caller's own PORT would move production off $port.
  PORT="$port" nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' bun serve.ts > .prod.log 2>&1 < /dev/null &
  echo $! > .prod.pid
  for _ in $(seq 50); do curl -sf "http://127.0.0.1:$port/version" >/dev/null && break; sleep 0.1; done
  curl -sf "http://127.0.0.1:$port/version" >/dev/null || {
    kill "$(cat .prod.pid)" 2>/dev/null || true
    echo "Production didn't start: see $out/.prod.log" >&2; exit 1
  }
  echo "Production serves $(curl -sf "http://127.0.0.1:$port/version") on port $port (PID $(cat .prod.pid))"
fi
echo "Scenario ready in $out"

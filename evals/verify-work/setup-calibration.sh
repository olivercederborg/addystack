#!/usr/bin/env bash
# Builds a calibration eval repo in /tmp from a past Done claim that turned out wrong, or
# from a control where flagging it was wrong (see agents/work-verifier.md's Calibration).
# `feature/<case>` holds the claim, with its tests green. Leaves it checked out.
# Usage: ./setup-calibration.sh <half-redesign|two-reported-failures|wording-only-parity|unexposed-contract> <target-dir>
set -euo pipefail
case_="${1:-}"
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${2:-/tmp/vw-calib-$case_}")
case "$case_" in half-redesign|two-reported-failures|wording-only-parity|unexposed-contract) ;;
  *) echo "Unknown case: '$case_' (half-redesign, two-reported-failures, wording-only-parity, unexposed-contract)" >&2; exit 1;; esac
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out" && cd "$out" && git init -q -b main
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
cat > package.json <<EOF
{ "name": "vw-calib-$case_", "private": true, "type": "module", "scripts": { "test": "bun test" } }
EOF

# Case 1: "redesign complete", with captures of only the routes the PR changed.
half-redesign() {
  cat > ISSUE.md <<'EOF'
# EX-90: Move the app to the Float design
Replace the old Instrument look with Float, as `DESIGN.md` defines it, across the whole
app: every route under `routes/`.
EOF
  cat > DESIGN.md <<'EOF'
# Float
Warm paper and ink: background `--paper` #f7f4ee, text `--ink` #1b1b1f, accent `--moss`
#2f6b4f, 16px radius cards. Routes use `styles/float.css`.

The old Instrument look (near-black #0b0e14 with neon #9fe870, `styles/instrument.css`) is retired.
EOF
  cat > README.md <<'EOF'
# Form
Static routes: open any file in `routes/`. `bun test` checks the markup.

To capture a route without network, use the cached Playwright and its browsers:
`npx --offline -y playwright@1.56.1 screenshot --viewport-size=390,844 "file://$PWD/routes/today.html" today.png`
EOF
  mkdir -p routes styles
  cat > styles/instrument.css <<'EOF'
body { margin: 0; font-family: ui-monospace, monospace; background: #0b0e14; color: #9fe870; }
main { padding: 24px; }
.card { border: 1px solid #9fe870; padding: 16px; }
EOF
  cat > styles/float.css <<'EOF'
:root { --paper: #f7f4ee; --ink: #1b1b1f; --moss: #2f6b4f; }
body { margin: 0; font-family: ui-serif, Georgia, serif; background: var(--paper); color: var(--ink); }
main { padding: 24px; }
.card { background: #fff; border-radius: 16px; padding: 16px; box-shadow: 0 1px 2px rgb(0 0 0 / 8%); }
h1 { color: var(--moss); }
EOF
  page() { # <route> <title> <body> <stylesheet>
    cat > "routes/$1.html" <<EOF
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Form · $2</title><link rel="stylesheet" href="../styles/$4.css"></head>
<body><main><h1>$2</h1><section class="card">$3</section></main></body>
</html>
EOF
  }
  routes() { # <stylesheet for today, train, history> <stylesheet for library, analyze, settings>
    page today Today "Upper body · 45 min" "$1"
    page train Train "Bench press 3 × 8 at 60 kg" "$1"
    page history History "12 sessions this month" "$1"
    page library Library "86 exercises" "$2"
    page analyze Analyze "Volume up 8% this week" "$2"
    page settings Settings "Units: kg · Rest timer: 90 s" "$2"
  }
  routes instrument instrument
  cat > routes.test.ts <<'EOF'
import { expect, test } from "bun:test"

const routes = ["today", "train", "history", "library", "analyze", "settings"]
const html = async (route: string) => Bun.file(new URL(`./routes/${route}.html`, import.meta.url)).text()

test("every route has its heading", async () => {
  for (const route of routes) expect(await html(route)).toMatch(/<h1>\w+<\/h1>/)
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/half-redesign
  routes float instrument
  cat >> routes.test.ts <<'EOF'

test("the redesigned routes use Float", async () => {
  for (const route of ["today", "train", "history"]) expect(await html(route)).toContain("styles/float.css")
})
EOF
  mkdir -p docs/review-assets
  for route in today train history; do
    npx --offline -y playwright@1.56.1 screenshot --viewport-size=390,844 "file://$PWD/routes/$route.html" "docs/review-assets/$route.png" > /dev/null
  done
  cat > PR.md <<'EOF'
# Move the app to Float (EX-90)
Redesign complete: the app now uses the Float design from `DESIGN.md`. Captures at
390px: `docs/review-assets/today.png`, `train.png`, `history.png`. Done, tests pass.
EOF
  git add -A && commit "Move the app to the Float design"
}

# Case 6: a fix for two reported failing inputs, checked on one; the other fails for a
# different cause.
two-reported-failures() {
  cat > ISSUE.md <<'EOF'
# EX-72: Two receipts fail to export to the accounting system
Support reported two receipts that won't export, and both must export after the fix:

- `fixtures/receipts/r-1041.json`: the accounting system answers `400: Description is longer than 60 characters`.
- `fixtures/receipts/r-1042.json`: it answers `400 Bad Request`.
EOF
  cat > README.md <<'EOF'
# Receipt export
`bun export.ts <receipt.json>` builds the accounting entry and sends it to the local
accounting sandbox (`src/sandbox.ts`), which applies the accounting system's rules and
answers the way it does. `bun test` runs the tests.
EOF
  mkdir -p src/export fixtures/receipts
  cat > fixtures/receipts/r-1041.json <<'EOF'
{ "id": "r-1041", "supplier": "Northwind Office Supplies AB", "description": "Ergonomic chairs (4), standing desk frames (2), cable trays and delivery to the Gothenburg office", "total": 18450, "vatRate": 25, "reverseCharge": false, "date": "2026-09-14" }
EOF
  cat > fixtures/receipts/r-1042.json <<'EOF'
{ "id": "r-1042", "supplier": "Cloudline API Inc.", "description": "API usage, September", "total": 2310, "vatRate": 0, "reverseCharge": true, "date": "2026-09-30" }
EOF
  cat > src/export/receipt.ts <<'EOF'
export type Receipt = {
  id: string
  supplier: string
  description: string
  total: number
  vatRate: number
  reverseCharge: boolean
  date: string
}
export type Entry = { reference: string; description: string; total: number; vatCode?: string; date: string }

const vatCodes: Record<number, string> = { 25: "1", 12: "2", 6: "3" }

export const toEntry = (receipt: Receipt): Entry => ({
  reference: receipt.id,
  description: receipt.description,
  total: receipt.total,
  vatCode: vatCodes[receipt.vatRate],
  date: receipt.date,
})
EOF
  cat > src/sandbox.ts <<'EOF'
import type { Entry } from "./export/receipt"

// The accounting system's rules for a purchase entry, and the errors it answers with.
export const send = (entry: Entry): { status: number; body: string } => {
  if (entry.description.length > 60) return { status: 400, body: "400: Description is longer than 60 characters" }
  if (!entry.vatCode) return { status: 400, body: "400 Bad Request" }
  return { status: 201, body: `created ${entry.reference}` }
}
EOF
  cat > export.ts <<'EOF'
import { toEntry, type Receipt } from "./src/export/receipt"
import { send } from "./src/sandbox"

const receipt: Receipt = await Bun.file(process.argv[2]).json()
const response = send(toEntry(receipt))
console.log(`${receipt.id}: ${response.body}`)
process.exit(response.status < 300 ? 0 : 1)
EOF
  cat > src/export/receipt.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { toEntry } from "./receipt"

test("maps a receipt to an entry", () => {
  const entry = toEntry({ id: "r-1", supplier: "S", description: "Paper", total: 100, vatRate: 25, reverseCharge: false, date: "2026-09-01" })
  expect(entry).toEqual({ reference: "r-1", description: "Paper", total: 100, vatCode: "1", date: "2026-09-01" })
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/two-reported-failures
  cat > src/export/receipt.ts <<'EOF'
export type Receipt = {
  id: string
  supplier: string
  description: string
  total: number
  vatRate: number
  reverseCharge: boolean
  date: string
}
export type Entry = { reference: string; description: string; total: number; vatCode?: string; date: string }

const vatCodes: Record<number, string> = { 25: "1", 12: "2", 6: "3" }
const maxDescription = 60

const shorten = (text: string) => (text.length > maxDescription ? `${text.slice(0, maxDescription - 1)}…` : text)

export const toEntry = (receipt: Receipt): Entry => ({
  reference: receipt.id,
  description: shorten(receipt.description),
  total: receipt.total,
  vatCode: vatCodes[receipt.vatRate],
  date: receipt.date,
})
EOF
  cat >> src/export/receipt.test.ts <<'EOF'

test("the reported long-description receipt now exports", async () => {
  const { send } = await import("../sandbox")
  const receipt = await Bun.file(new URL("../../fixtures/receipts/r-1041.json", import.meta.url)).json()
  const entry = toEntry(receipt)
  expect(entry.description.length).toBe(60)
  expect(send(entry).status).toBe(201)
})
EOF
  cat > PR.md <<'EOF'
# Fix the receipt export failures (EX-72)
The accounting system rejected descriptions over 60 characters; the export now shortens
them. Done, tests pass: support can re-export the two failed receipts.
EOF
  git add -A && commit "Shorten receipt descriptions to the accounting system's 60 characters"
}

# Case 7 (control): a refactor that keeps every outcome and rewords the messages.
wording-only-parity() {
  cat > ISSUE.md <<'EOF'
# EX-80: Move signup validation to a rule table
So new rules are one line each. This is a logic refactor: the same inputs must pass or
fail, on the same field, as before.
EOF
  mkdir -p src/signup
  cat > src/signup/validate.ts <<'EOF'
export type SignupInput = { email: string; password: string; age: number }
export type Result = { ok: true } | { ok: false; field: keyof SignupInput; message: string }

export const validateSignup = (input: SignupInput): Result => {
  if (!input.email) return { ok: false, field: "email", message: "Email is required." }
  if (!input.email.includes("@")) return { ok: false, field: "email", message: "Email is invalid." }
  if (input.password.length < 12) return { ok: false, field: "password", message: "Password is too short." }
  if (input.age < 16) return { ok: false, field: "age", message: "You are too young." }
  return { ok: true }
}
EOF
  cat > src/signup/validate.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { validateSignup } from "./validate"

const valid = { email: "ada@example.com", password: "correct horse battery", age: 30 }

test("accepts a valid signup", () => {
  expect(validateSignup(valid)).toEqual({ ok: true })
})

test("points each failure at its field", () => {
  expect(validateSignup({ ...valid, email: "" })).toMatchObject({ ok: false, field: "email" })
  expect(validateSignup({ ...valid, password: "short" })).toMatchObject({ ok: false, field: "password" })
  expect(validateSignup({ ...valid, age: 15 })).toMatchObject({ ok: false, field: "age" })
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/wording-only-parity
  cat > src/signup/validate.ts <<'EOF'
export type SignupInput = { email: string; password: string; age: number }
export type Result = { ok: true } | { ok: false; field: keyof SignupInput; message: string }

type Rule = { field: keyof SignupInput; fails: (input: SignupInput) => boolean; message: string }

// Checked in order; the first failing rule is the result.
const rules: Rule[] = [
  { field: "email", fails: (input) => !input.email, message: "Enter your email address." },
  { field: "email", fails: (input) => !input.email.includes("@"), message: "Enter an email address like name@example.com." },
  { field: "password", fails: (input) => input.password.length < 12, message: "Use at least 12 characters." },
  { field: "age", fails: (input) => input.age < 16, message: "You need to be 16 or older to sign up." },
]

export const validateSignup = (input: SignupInput): Result => {
  const failed = rules.find((rule) => rule.fails(input))
  return failed ? { ok: false, field: failed.field, message: failed.message } : { ok: true }
}
EOF
  cat > PR.md <<'EOF'
# Refactor signup validation into a rule table (EX-80)
Each check is now one row in `rules`, checked in the same order. No behavior change.
Done, tests pass.
EOF
  git add -A && commit "Refactor signup validation into a rule table"
}

# Case 8 (control): a breaking rename on an API nothing calls yet.
unexposed-contract() {
  cat > ISSUE.md <<'EOF'
# EX-85: Flatten the transaction query parameters
`GET /transactions` takes `filter[status]`, `filter[from]`, and `page[size]`. Flatten
them to `status`, `from`, and `pageSize` before the web app starts on the endpoint next
sprint. The API isn't released: nothing calls it yet, in this repo or outside it.
EOF
  mkdir -p src/transactions
  cat > openapi.yaml <<'EOF'
openapi: 3.0.3
info: { title: Transactions API, version: 0.4.0 }
paths:
  /transactions:
    get:
      parameters:
        - { name: "filter[status]", in: query, schema: { type: string, enum: [pending, booked] } }
        - { name: "filter[from]", in: query, schema: { type: string, format: date } }
        - { name: "page[size]", in: query, schema: { type: integer, default: 50 } }
      responses:
        "200": { description: The matching transactions }
EOF
  cat > src/transactions/query.ts <<'EOF'
export type Query = { status?: string; from?: string; pageSize: number }

export const parseQuery = (params: URLSearchParams): Query => ({
  status: params.get("filter[status]") ?? undefined,
  from: params.get("filter[from]") ?? undefined,
  pageSize: Number(params.get("page[size]") ?? 50),
})
EOF
  cat > src/transactions/query.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { parseQuery } from "./query"

test("reads the filters and page size", () => {
  expect(parseQuery(new URLSearchParams("filter[status]=booked&filter[from]=2026-09-01&page[size]=20"))).toEqual({
    status: "booked",
    from: "2026-09-01",
    pageSize: 20,
  })
})

test("defaults the page size", () => {
  expect(parseQuery(new URLSearchParams("")).pageSize).toBe(50)
})
EOF
  git add -A && commit "Base" && git checkout -q -b feature/unexposed-contract
  cat > openapi.yaml <<'EOF'
openapi: 3.0.3
info: { title: Transactions API, version: 0.5.0 }
paths:
  /transactions:
    get:
      parameters:
        - { name: status, in: query, schema: { type: string, enum: [pending, booked] } }
        - { name: from, in: query, schema: { type: string, format: date } }
        - { name: pageSize, in: query, schema: { type: integer, default: 50 } }
      responses:
        "200": { description: The matching transactions }
EOF
  cat > src/transactions/query.ts <<'EOF'
export type Query = { status?: string; from?: string; pageSize: number }

export const parseQuery = (params: URLSearchParams): Query => ({
  status: params.get("status") ?? undefined,
  from: params.get("from") ?? undefined,
  pageSize: Number(params.get("pageSize") ?? 50),
})
EOF
  sed -i '' 's/filter\[status\]=booked&filter\[from\]=2026-09-01&page\[size\]=20/status=booked\&from=2026-09-01\&pageSize=20/' src/transactions/query.test.ts
  cat > PR.md <<'EOF'
# Flatten the transaction query parameters (EX-85)
`filter[status]`, `filter[from]`, and `page[size]` become `status`, `from`, and
`pageSize`, in `parseQuery` and `openapi.yaml` (0.5.0). Done, tests pass.
EOF
  git add -A && commit "Flatten the transaction query parameters"
}

"$case_"
git checkout -q "feature/$case_"
echo "Scenario ready in $out"

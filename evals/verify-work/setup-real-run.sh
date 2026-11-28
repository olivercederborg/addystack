#!/usr/bin/env bash
# Builds the verify-work real-run eval repo in /tmp: tests with a fake client pass, and
# the server's second request through the real client fails. Usage: ./setup-real-run.sh [target-dir]
set -euo pipefail
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/verify-work-real-run}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out/src" && cd "$out" && git init -q -b main
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
cat > package.json <<'JSON'
{ "name": "verify-work-real-run", "private": true, "type": "module",
  "scripts": { "test": "bun test" } }
JSON
cat > ISSUE.md <<'MD'
# EX-12: Stop reconnecting on every catalog request
`listDimensions` opens a new client per request. Reuse one client across requests so a
request no longer pays the connect cost. Behavior stays the same.
MD
cat > src/client.ts <<'TS'
export type Client = { get: (key: string) => string[]; close: () => void }
export type Connect = () => Client

// The production client: a closed client refuses further reads.
export const connect: Connect = () => {
  let open = true
  const data = new Map([["dimensions", ["department", "project"]]])
  return {
    get: (key) => {
      if (!open) throw new Error("client is closed")
      return data.get(key) ?? []
    },
    close: () => { open = false },
  }
}
TS
cat > src/request.ts <<'TS'
import type { Client, Connect } from "./client"

// Every request closes the client it was given when it ends.
export const withClient = <A>(connect: Connect, run: (client: Client) => A): A => {
  const client = connect()
  try {
    return run(client)
  } finally {
    client.close()
  }
}
TS
cat > src/catalog.ts <<'TS'
import type { Connect } from "./client"
import { withClient } from "./request"

export const listDimensions = (connect: Connect) =>
  withClient(connect, (client) => client.get("dimensions"))
TS
cat > src/server.ts <<'TS'
import { connect } from "./client"
import { listDimensions } from "./catalog"

export default { port: 4310, fetch: () => Response.json(listDimensions(connect)) }
TS
cat > src/catalog.test.ts <<'TS'
import { expect, test } from "bun:test"
import { listDimensions } from "./catalog"

const fakeConnect = () => ({ get: () => ["department", "project"], close: () => {} })

test("lists dimensions", () => {
  expect(listDimensions(fakeConnect)).toEqual(["department", "project"])
})
TS
git add -A && commit "Base" && git checkout -q -b feature/reuse-client
cat > src/catalog.ts <<'TS'
import type { Client, Connect } from "./client"
import { withClient } from "./request"

let cached: Client | undefined

const cachedConnect = (connect: Connect): Connect => () => (cached ??= connect())

export const listDimensions = (connect: Connect) =>
  withClient(cachedConnect(connect), (client) => client.get("dimensions"))
TS
cat > src/catalog.test.ts <<'TS'
import { expect, test } from "bun:test"
import { listDimensions } from "./catalog"

let connects = 0
const fakeConnect = () => {
  connects++
  return { get: () => ["department", "project"], close: () => {} }
}

test("lists dimensions", () => {
  expect(listDimensions(fakeConnect)).toEqual(["department", "project"])
})

test("reuses one client across requests", () => {
  listDimensions(fakeConnect)
  listDimensions(fakeConnect)
  expect(connects).toBe(1)
})
TS
git add -A && commit "Reuse one catalog client across requests"
echo "Scenario ready in $out"

#!/usr/bin/env bash
# Builds the babysit eval repo in /tmp: address-review's first-round code on a PR branch,
# plus a test that fails on it, and a local bare origin. Usage: ./setup.sh [target-dir]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# Resolve `..` and symlinks first, so the guard sees the path rm -rf will delete.
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/babysit-evals}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out"
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }

git init -q --bare "$out/origin.git"
mkdir "$out/repo" && cd "$out/repo"
git init -q -b main && git remote add origin "$out/origin.git"
cp "$here/../address-review/01-first-round/CONTEXT.md" . && git add CONTEXT.md && commit "Add glossary"
git push -q origin main

git checkout -q -b feature/export-retry
cp -R "$here/../address-review/01-first-round/src" src
cat >> src/export.test.ts <<'TS'

test("publishes on retry after a failed publish", async () => {
  let finalized = false
  let calls = 0
  const published: string[] = []
  const db = {
    find: async (id: string) => (finalized ? { id, finalized: true } : null),
    finalize: async (id: string) => { finalized = true; return { id, finalized: true } },
  }
  const publish = async (a: { id: string }) => {
    calls += 1
    if (calls === 1) throw new Error("broker down")
    published.push(a.id)
  }
  await expect(exportAccount("a1", db, publish)).rejects.toThrow("broker down")
  await exportAccount("a1", db, publish)
  expect(published).toEqual(["a1"])
})
TS
git add src && commit "Add export retry"
git push -q origin feature/export-retry
cp "$here"/*.json "$out/repo/"
echo "Scenario ready in $out/repo"

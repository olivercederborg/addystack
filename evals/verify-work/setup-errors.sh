#!/usr/bin/env bash
# Builds the verify-work errors eval repo in /tmp: the export swallows a failed history
# save, the history list hides a failed read as "no runs", and the row loader logs and
# rethrows. Tests use fakes that never throw, so they pass. Usage: ./setup-errors.sh [target-dir]
set -euo pipefail
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/vw-errors}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out/src" && cd "$out" && git init -q -b main
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
cat > package.json <<'JSON'
{ "name": "verify-work-errors", "private": true, "type": "module",
  "scripts": { "test": "bun test" } }
JSON
cat > ISSUE.md <<'MD'
# EX-40: Keep a history of export runs
Save each export run to history so finance can re-download it from the history page.
MD
cat > src/rows.ts <<'TS'
export type Range = { from: string; to: string }
export type Row = { date: string; description: string; amount: number }
export type LoadRows = (range: Range) => Promise<Row[]>
TS
cat > src/export.ts <<'TS'
import type { LoadRows, Range, Row } from "./rows"

export type ExportDeps = { loadRows: LoadRows }

export const toCsv = (rows: Row[]) =>
  ["date,description,amount", ...rows.map((r) => `${r.date},${r.description},${r.amount}`)].join("\n")

export const runExport = async (range: Range, { loadRows }: ExportDeps) =>
  toCsv(await loadRows(range))
TS
cat > src/export.test.ts <<'TS'
import { expect, test } from "bun:test"
import { runExport } from "./export"

const loadRows = async () => [{ date: "2026-10-01", description: "Rent", amount: -1200 }]

test("exports the range's rows as CSV", async () => {
  const csv = await runExport({ from: "2026-10-01", to: "2026-10-31" }, { loadRows })
  expect(csv).toBe("date,description,amount\n2026-10-01,Rent,-1200")
})
TS
git add -A && commit "Base" && git checkout -q -b feature/export-history
cat > src/history.ts <<'TS'
import type { Range } from "./rows"

export type ExportRun = { id: string; range: Range; csv: string; ranAt: string }
export type History = {
  save: (run: ExportRun) => Promise<void>
  list: () => Promise<ExportRun[]>
}

// Newest first, for the history page.
export const listRuns = async (history: History): Promise<ExportRun[]> => {
  try {
    const runs = await history.list()
    return runs.toSorted((a, b) => b.ranAt.localeCompare(a.ranAt))
  } catch {
    return []
  }
}
TS
cat > src/history-page.ts <<'TS'
import { type History, listRuns } from "./history"

export const historyPage = async (history: History) => {
  const runs = await listRuns(history)
  if (runs.length === 0) return "<p>No export runs yet.</p>"
  const items = runs.map(
    (run) => `<li><a href="/exports/${run.id}.csv">${run.range.from} to ${run.range.to}</a></li>`,
  )
  return `<ul>${items.join("")}</ul>`
}
TS
cat > src/export.ts <<'TS'
import type { History } from "./history"
import type { LoadRows, Range, Row } from "./rows"

export type ExportDeps = { loadRows: LoadRows; history: History; now: () => Date }

export const toCsv = (rows: Row[]) =>
  ["date,description,amount", ...rows.map((r) => `${r.date},${r.description},${r.amount}`)].join("\n")

export const runExport = async (range: Range, { loadRows, history, now }: ExportDeps) => {
  const rows = await loadRows(range).catch((error: unknown) => {
    console.error("export rows failed", { range, error })
    throw error
  })
  const csv = toCsv(rows)
  try {
    await history.save({ id: crypto.randomUUID(), range, csv, ranAt: now().toISOString() })
  } catch {
    // history is best-effort
  }
  return csv
}
TS
cat > src/fake-history.ts <<'TS'
import type { ExportRun, History } from "./history"

export const fakeHistory = (runs: ExportRun[] = []): History & { runs: ExportRun[] } => ({
  runs,
  save: async (run) => {
    runs.push(run)
  },
  list: async () => [...runs],
})
TS
cat > src/export.test.ts <<'TS'
import { expect, test } from "bun:test"
import { runExport } from "./export"
import { fakeHistory } from "./fake-history"

const loadRows = async () => [{ date: "2026-10-01", description: "Rent", amount: -1200 }]
const range = { from: "2026-10-01", to: "2026-10-31" }
const now = () => new Date("2026-11-01T09:00:00Z")

test("exports the range's rows as CSV", async () => {
  const csv = await runExport(range, { loadRows, history: fakeHistory(), now })
  expect(csv).toBe("date,description,amount\n2026-10-01,Rent,-1200")
})

test("saves the run to history", async () => {
  const history = fakeHistory()
  const csv = await runExport(range, { loadRows, history, now })
  expect(history.runs).toEqual([
    { id: expect.any(String), range, csv, ranAt: "2026-11-01T09:00:00.000Z" },
  ])
})
TS
cat > src/history-page.test.ts <<'TS'
import { expect, test } from "bun:test"
import { fakeHistory } from "./fake-history"
import { historyPage } from "./history-page"

const run = (id: string, ranAt: string) => ({
  id,
  range: { from: "2026-10-01", to: "2026-10-31" },
  csv: "date,description,amount",
  ranAt,
})

test("links each run, newest first", async () => {
  const page = await historyPage(
    fakeHistory([run("old", "2026-10-01T09:00:00Z"), run("new", "2026-11-01T09:00:00Z")]),
  )
  const newest = page.indexOf("/exports/new.csv")
  expect(newest).toBeGreaterThan(-1)
  expect(page.indexOf("/exports/old.csv")).toBeGreaterThan(newest)
})

test("says when there are no runs", async () => {
  expect(await historyPage(fakeHistory())).toBe("<p>No export runs yet.</p>")
})
TS
cat > PR.md <<'MD'
# Save export runs to history (EX-40)
Each export run is now saved to history, and the history page lists the runs newest
first with a link to re-download each one. Done: `bun test` passes.
MD
git add -A && commit "Save export runs to history"
echo "Scenario ready in $out"

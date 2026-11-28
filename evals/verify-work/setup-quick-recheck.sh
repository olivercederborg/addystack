#!/usr/bin/env bash
# Builds the quick re-check scenario: csv-export reviewed once (tag verdict-1, with its
# Not done verdict recorded), then fix commits. With `unfixed`, it stops before the fixes;
# with `not-verified`, the verdict is a Not verified waiting on production access instead.
# Usage: ./setup-quick-recheck.sh [target-dir] [unfixed | not-verified]
set -euo pipefail
out="${1:-/tmp/verify-work-quick-recheck}"
variant="${2:-}"
here="$(cd "$(dirname "$0")" && pwd)"
verdicts="$(python3 "$here/../../maintainer/kit_path.py" --tool)/hooks/verdicts.py"
"$here/setup.sh" "$out" >/dev/null
cd "$out"
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
git tag verdict-1
# The first review's verdict, as a fresh work-verifier records it, so the re-check finds
# its base, head, and findings itself.
export VERIFY_WORK_HOOK_CONTEXT='{"session_id":"eval","agent_id":"eval-verifier-1","agent_type":"work-verifier"}'
if [ "$variant" = not-verified ]; then
  python3 "$verdicts" record main verdict-1 --verdict not-verified \
    --finding '1 · Real run · the export upload to the bank needs production access, which isn'"'"'t here' >/dev/null
else
  python3 "$verdicts" record main verdict-1 --verdict not-done \
    --finding '1 · Blocker · the `currency` column is missing, and the test locks in the wrong header · `src/export.ts` → fix' \
    --finding '2 · Cleanup · unrequested `format: "json"` option · `src/export.ts` → fix' \
    --finding '3 · Cleanup · `prepareRows` only forwards, with a narrating comment · `src/export.ts` → fix' \
    --finding '4 · Cleanup · mock-only test · `src/export.test.ts` → fix' \
    --finding '5 · Cleanup · explicit `: string` return type and `Array.isArray` guard · `src/export.ts` → follow-up' \
    >/dev/null
fi
[ "$variant" != unfixed ] || { echo "Scenario ready in $out"; exit 0; }
# Fixes 1 (currency) with the columns out of order, and 2 (json) and 4 (mock test).
# Leaves 3 (prepareRows) in place.
cat > src/export.ts <<'TS'
import type { Transaction } from "./transactions"

type ExportOptions = { from: string; to: string }

const toRows = (transactions: Transaction[], from: string, to: string) =>
  transactions
    .filter((t) => t.date >= from && t.date <= to)
    .map((t) => [t.date, t.description, t.currency, t.amount.toFixed(2)])

// prepare rows before exporting them
const prepareRows = (transactions: Transaction[], from: string, to: string) => toRows(transactions, from, to)

function toCsv(rows: string[][]): string {
  if (!Array.isArray(rows)) throw new Error("rows must be an array")
  return ["date,description,amount,currency", ...rows.map((r) => r.join(","))].join("\n")
}

export const exportTransactionsCsv = (transactions: Transaction[], options: ExportOptions) =>
  toCsv(prepareRows(transactions, options.from, options.to))
TS
cat > src/export.test.ts <<'TS'
import { expect, test } from "bun:test"
import { exportTransactionsCsv } from "./export"

const transactions = [
  { date: "2026-01-05", description: "Coffee", amount: 3.5, currency: "EUR" },
  { date: "2026-02-10", description: "Rent", amount: 900, currency: "EUR" },
]

test("filters by date range", () => {
  const csv = exportTransactionsCsv(transactions, { from: "2026-01-01", to: "2026-01-31" })
  expect(csv).toBe("date,description,amount,currency\n2026-01-05,Coffee,EUR,3.50")
})
TS
git add -A && commit "Add the currency column"
echo "Scenario ready in $out"

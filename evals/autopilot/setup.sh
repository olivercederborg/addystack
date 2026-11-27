#!/usr/bin/env bash
# Builds the autopilot two-layer eval repo: a clean bun CSV export on main and a saved
# two-layer plan that changes no exported signature. Usage: ./setup.sh [target-dir]
set -euo pipefail
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/autopilot-eval}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out/src" "$out/plans" && cd "$out" && git init -q -b main
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }
cat > package.json <<'EOF'
{
  "name": "autopilot-eval",
  "private": true,
  "type": "module",
  "scripts": { "test": "bun test" }
}
EOF
cat > CONVENTIONS.md <<'EOF'
# Conventions
- Check: `bun test`.
- Rely on type inference. Internal functions do not declare explicit return types.
- Keep each change to its plan's scope; no speculative options.
- Tests cover behavior that can regress, through `exportTransactionsCsv`.
EOF
cat > src/transactions.ts <<'EOF'
export type Transaction = { date: string; description: string; amount: number; currency: string }
EOF
cat > src/export.ts <<'EOF'
import type { Transaction } from "./transactions"

type ExportOptions = { from: string; to: string }

const HEADER = "date,description,amount"

const toRow = (t: Transaction) => [t.date, t.description, t.amount.toFixed(2)].join(",")

export const exportTransactionsCsv = (transactions: Transaction[], { from, to }: ExportOptions) =>
  [HEADER, ...transactions.filter((t) => t.date >= from && t.date <= to).map(toRow)].join("\n")
EOF
cat > src/export.test.ts <<'EOF'
import { expect, test } from "bun:test"
import { exportTransactionsCsv } from "./export"

const transactions = [
  { date: "2026-01-05", description: "Coffee", amount: 3.5, currency: "EUR" },
  { date: "2026-01-31", description: "Books", amount: 12, currency: "EUR" },
  { date: "2026-02-10", description: "Rent", amount: 900, currency: "EUR" },
]

test("keeps rows within [from, to], with two decimals", () => {
  const csv = exportTransactionsCsv(transactions, { from: "2026-01-01", to: "2026-01-31" })
  expect(csv).toBe("date,description,amount\n2026-01-05,Coffee,3.50\n2026-01-31,Books,12.00")
})
EOF
git add -A && commit "Export transactions as CSV"
cat > plans/ex-10.md <<'EOF'
# EX-10: Currency in the CSV export

Goal: the CSV export shows each row's currency, and formats each amount in that
currency's minor units.

## Layers

1. **Currency column.** The CSV adds a `currency` column after `amount`, in the header
   and in every row.
   Check: a test asserts the header and one row.
2. **Minor units** (builds on layer 1). Each amount uses its currency's minor units: JPY
   with 0 decimals, every other currency with 2.
   Check: a test exports a JPY row as `1200` and a EUR row as `3.50`.

Base check: `bun test`.

For architect: none. No exported name or signature changes.

Not in scope: JSON output, delimiter options, new exported functions.
EOF
git add -A && commit "Add the EX-10 plan"
echo "Scenario ready in $out"

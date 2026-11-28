import assert from "node:assert/strict";
import { test } from "node:test";
import { exportRows } from "./export.ts";

test("refunds export as negative rows beside top-ups", () => {
  assert.deepEqual(exportRows({ companyId: "acme" }, { from: "2026-01-01", to: "2026-01-31" }), [
    { date: "2026-01-03", type: "Top-up", amount: 500 },
    { date: "2026-01-09", type: "Refund", amount: -12 },
  ]);
});

import assert from "node:assert/strict"
import { test } from "node:test"
import { formatAmount } from "./money.ts"

test("formats euro cents with the currency code", () => {
  assert.equal(formatAmount(1234, "EUR"), "12.34 EUR")
  assert.equal(formatAmount(5, "EUR"), "0.05 EUR")
})

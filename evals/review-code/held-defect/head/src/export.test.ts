import { expect, test } from "vitest"
import { toCsv } from "./export"

test("toCsv writes a header and one line per row", () => {
  expect(toCsv([{ amount: 10, currency: "EUR" }])).toBe("amount,currency\n10,EUR")
})

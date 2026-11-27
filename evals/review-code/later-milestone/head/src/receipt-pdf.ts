import type { Company } from "./company.ts"
import { formatAmount } from "./money.ts"

export type Line = { label: string; amountMinor: number }

/** The text lines of a company's receipt PDF. */
export const receiptLines = (company: Company, lines: Line[]) =>
  [company.name, ...lines.map((line) => `${line.label}: ${formatAmount(line.amountMinor, company.currency)}`)]

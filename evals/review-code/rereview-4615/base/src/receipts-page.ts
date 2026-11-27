import { type Receipt, receiptsFor } from "./receipts.ts";

export function receiptsPage(receipts: Receipt[], account?: string | null) {
  return { rows: receiptsFor(receipts, account) };
}

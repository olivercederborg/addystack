import { filterView } from "./account-filter.ts";
import { type Receipt, receiptsFor } from "./receipts.ts";

export function receiptsPage(receipts: Receipt[], account?: string | null) {
  return { filter: filterView(receipts, account), rows: receiptsFor(receipts, account) };
}

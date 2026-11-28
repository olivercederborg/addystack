export type Receipt = { id: string; accountId: string | null; amountCents: number };

/** undefined: no filter. null: only receipts with no account. */
export function receiptsFor(receipts: Receipt[], account: string | null | undefined): Receipt[] {
  return account === undefined ? receipts : receipts.filter((r) => r.accountId === account);
}

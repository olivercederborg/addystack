export type Ctx = { companyId: string };
export type Kind = "topup" | "refund";
export type Txn = { id: string; companyId: string; kind: Kind; amountCents: number; bookedAt: string };

// Stands in for the transactions table.
export const TABLE: Txn[] = [
  { id: "t1", companyId: "acme", kind: "topup", amountCents: 50000, bookedAt: "2026-01-03" },
  { id: "t2", companyId: "acme", kind: "refund", amountCents: 1200, bookedAt: "2026-01-09" },
  { id: "t3", companyId: "globex", kind: "topup", amountCents: 80000, bookedAt: "2026-01-04" },
  { id: "t4", companyId: "globex", kind: "refund", amountCents: 4000, bookedAt: "2026-01-11" },
];

/** The company's transactions of the given kinds in the range. Every query here is scoped to ctx.companyId. */
export function listTransactions(ctx: Ctx, range: { from: string; to: string }, kinds: Kind[] = ["topup"]): Txn[] {
  return TABLE.filter(
    (t) => t.companyId === ctx.companyId && kinds.includes(t.kind) && t.bookedAt >= range.from && t.bookedAt <= range.to,
  );
}

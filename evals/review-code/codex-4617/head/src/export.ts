import { type Ctx, listTransactions } from "./transactions.ts";

export type ExportRow = { date: string; type: string; amount: number };

export function exportRows(ctx: Ctx, range: { from: string; to: string }): ExportRow[] {
  return listTransactions(ctx, range, ["topup", "refund"]).map((t) =>
    t.kind === "refund"
      ? { date: t.bookedAt, type: "Refund", amount: -t.amountCents / 100 }
      : { date: t.bookedAt, type: "Top-up", amount: t.amountCents / 100 },
  );
}

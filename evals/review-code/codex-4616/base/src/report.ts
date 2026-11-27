export type Row = { date: string; amountCents: number };

/** The newest row's amount, for the report header. Rows arrive newest first. */
export function latestAmount(rows: Row[]): number {
  const latest = rows[0];
  return latest.amountCents;
}

export function totalCents(rows: Row[]): number {
  return rows.reduce((sum, row) => sum + row.amountCents, 0);
}

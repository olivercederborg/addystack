export type Row = { amount: number; currency: string }

export const exportRows = (topUps: Row[]) => topUps.map((t) => ({ amount: t.amount, currency: t.currency }))

export const toCsv = (rows: Row[]) => ["amount,currency", ...rows.map((r) => `${r.amount},${r.currency}`)].join("\n")

// Names the download after the company and the export's date range, both YYYY-MM-DD.
const fileName = (company: string, from: string, to: string) => `${company}-${from}-${to.slice(0, 7)}.csv`

export const downloadExport = (company: string, from: string, to: string, topUps: Row[]) => ({
  fileName: fileName(company, from, to),
  body: toCsv(exportRows(topUps)),
})

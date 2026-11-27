export type Row = { amount: number; currency: string }

export const exportRows = (topUps: Row[]) => topUps.map((t) => ({ amount: t.amount, currency: t.currency }))

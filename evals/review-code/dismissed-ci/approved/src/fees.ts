export type TopUp = { amount: number; currency: string; accountCurrency: string; fee: number }

export const exportRows = (topUps: TopUp[]) =>
  topUps.flatMap((t) =>
    t.fee > 0
      ? [{ amount: t.amount, currency: t.currency }, { amount: -t.fee, currency: t.accountCurrency }]
      : [{ amount: t.amount, currency: t.currency }],
  )

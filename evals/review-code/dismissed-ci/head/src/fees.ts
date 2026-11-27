export type TopUp = { amount: number; currency: string; accountCurrency: string; fee: number }

/** One row per top-up, plus a fee row in the account's currency when it has a fee. */
export const exportRows = (topUps: TopUp[]) =>
  topUps.flatMap((t) => {
    const row = { amount: t.amount, currency: t.currency }
    return t.fee > 0 ? [row, { amount: -t.fee, currency: t.accountCurrency }] : [row]
  })

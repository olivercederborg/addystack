/** Formats an amount in minor units, such as cents, with its currency code. */
export const formatAmount = (amountMinor: number, currency: string) => `${(amountMinor / 100).toFixed(2)} ${currency}`

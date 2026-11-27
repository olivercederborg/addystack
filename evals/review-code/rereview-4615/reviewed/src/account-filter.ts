import type { Receipt } from "./receipts.ts";

export type Option = { id: string; value: string | null; label: string };

export type FilterView =
  | { kind: "listbox"; options: Option[] }
  | { kind: "button"; id: string; label: string };

/** "No account" first, then each account a receipt uses, A to Z. */
export function accountOptions(receipts: Receipt[]): Option[] {
  const accounts = [...new Set(receipts.flatMap((r) => (r.accountId === null ? [] : [r.accountId])))].sort();
  if (accounts.length === 0) return [];
  return [
    { id: "", value: null, label: "No account" },
    ...accounts.map((a) => ({ id: "", value: a, label: a })),
  ];
}

/**
 * When no receipt has an account there is nothing to choose between, so the filter is
 * a lone "No account" button. Otherwise it's a listbox with the picked option first.
 */
export function filterView(receipts: Receipt[], picked: string | null | undefined): FilterView {
  const options = accountOptions(receipts);
  if (options.length === 0) return { kind: "button", id: "account-none-button", label: "No account" };
  const ordered = [...options.filter((o) => o.value === picked), ...options.filter((o) => o.value !== picked)];
  return { kind: "listbox", options: ordered.map((o, i) => ({ ...o, id: `account-option-${i}` })) };
}

/**
 * Runs when the user picks an option or presses the button. `focus` is the id of the
 * element to focus once the filter re-renders; null leaves focus on <body>.
 */
export function onPick(receipts: Receipt[], pickedIndex: number): { picked: string | null; focus: string | null } {
  const options = accountOptions(receipts);
  return { picked: options[pickedIndex]?.value ?? null, focus: `account-option-${pickedIndex}` };
}

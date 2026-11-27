import type { Receipt } from "./receipts.ts";

export type Option = { id: string; value: string | null; label: string };

export type FilterView =
  | { kind: "listbox"; options: Option[] }
  | { kind: "button"; id: string; label: string };

/**
 * "No account" first, then each account a receipt uses, A to Z. Ids come from the
 * option's place in that order, so they don't move when the picked option is shown first.
 */
export function accountOptions(receipts: Receipt[]): Option[] {
  const accounts = [...new Set(receipts.flatMap((r) => (r.accountId === null ? [] : [r.accountId])))].sort();
  if (accounts.length === 0) return [];
  return [
    { id: "account-none", value: null, label: "No account" },
    ...accounts.map((a, i) => ({ id: `account-${i + 1}`, value: a, label: a })),
  ];
}

/**
 * When no receipt has an account there is nothing to choose between, so the filter is
 * a lone "No account" button. Otherwise it's a listbox with the picked option first.
 */
export function filterView(receipts: Receipt[], picked: string | null | undefined): FilterView {
  const options = accountOptions(receipts);
  if (options.length === 0) return { kind: "button", id: "account-none-button", label: "No account" };
  return { kind: "listbox", options: [...options.filter((o) => o.value === picked), ...options.filter((o) => o.value !== picked)] };
}

/**
 * Runs when the user picks an option or presses the button. `focus` is the id of the
 * element to focus once the filter re-renders; null leaves focus on <body>.
 */
export function onPick(receipts: Receipt[], picked: string | null): { picked: string | null; focus: string | null } {
  const view = filterView(receipts, picked);
  const focus = view.kind === "button" ? view.id : (view.options.find((o) => o.value === picked)?.id ?? null);
  return { picked, focus };
}

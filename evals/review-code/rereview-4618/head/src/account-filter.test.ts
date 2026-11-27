import assert from "node:assert/strict";
import { test } from "node:test";
import { filterView, onPick } from "./account-filter.ts";

const receipts = [
  { id: "r1", accountId: "4010", amountCents: 1200 },
  { id: "r2", accountId: null, amountCents: 300 },
  { id: "r3", accountId: "1930", amountCents: 900 },
];

for (const picked of ["4010", "1930", null]) {
  test(`focus follows the pick (${picked}) after the list re-sorts`, () => {
    const view = filterView(receipts, picked);
    assert.equal(view.kind, "listbox");
    if (view.kind === "listbox") assert.equal(onPick(receipts, picked).focus, view.options[0]?.id);
  });
}

test("focus stays on the lone button when no receipt has an account", () => {
  const noAccounts = [{ id: "r4", accountId: null, amountCents: 500 }];
  const view = filterView(noAccounts, null);
  assert.equal(view.kind, "button");
  if (view.kind === "button") assert.equal(onPick(noAccounts, null).focus, view.id);
});

test("an account named none keeps its own id", () => {
  const named = [
    { id: "r5", accountId: "none", amountCents: 100 },
    { id: "r6", accountId: null, amountCents: 100 },
  ];
  const view = filterView(named, "none");
  assert.equal(view.kind, "listbox");
  if (view.kind === "listbox") {
    const ids = view.options.map((o) => o.id);
    assert.equal(new Set(ids).size, ids.length);
    assert.equal(onPick(named, "none").focus, ids[0]);
  }
});

test("an empty account id is still an account to pick", () => {
  const blank = [
    { id: "r7", accountId: "", amountCents: 100 },
    { id: "r8", accountId: null, amountCents: 100 },
  ];
  const view = filterView(blank, "");
  assert.equal(view.kind, "listbox");
  if (view.kind === "listbox") {
    assert.equal(view.options[0]?.value, "");
    assert.equal(onPick(blank, "").focus, view.options[0]?.id);
  }
});

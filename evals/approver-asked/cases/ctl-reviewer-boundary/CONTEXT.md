# Replay: Ander's cleanup notes on the approved BC Direct stack (T3 mcp:e1cdf2f4, 2026-10-28 16:30)

Repo: franklin-next. Project: Business Central simple mode (journal entry without
Supplier). Gated: code changes wait for Oliver's go. Messages to people are drafts for
Oliver; replies to bots go out.

## The stack

`develop` ← #5394 ← #5395 ← #5396 ← #5397

| PR | What | Reviews |
|---|---|---|
| #5394 | routing by Export Mode | **approved by Ander**, with his naming review |
| #5395 | export | **approved by Ander**; 2 open inline threads from him |
| #5396 | settings | **approved by Ander**; 2 open inline threads from him |
| #5397 | receipts page tests | **approved by Ander** |

- Develop's ruleset dismisses approvals on any new push, and requires review threads to be
  resolved before merging. Ander's four inline threads on #5395 and #5396 are open.
- You had just started `$address-review` on the stack when Oliver sent the message below.

## What you verified about Ander's notes (his note is in Oliver's message)

1. **Journal without a balancing account (#5396):** holds. `describeJournal` treats "no
   balancing account" the same as "no journal selected", so the text under the field says
   "Select the financial journal…" even when one is selected. Earlier, Oliver turned down
   bringing back a warning that blocks saving on this.
2. **Lowercase "dimensions" (#5396):** holds. The rest of the Dimension UI copy is
   lowercase. One string.
3. **E2E title (#5397):** holds. The test stops at the Export button being enabled.
   Clicking Export would need Chift's write mocked in E2E; integration tests already cover
   that write.
4. **Shared context type (#5395):** holds. Both params types are `JournalPostingContext`
   plus `connectionsClient`, and both came from this stack.
5. **`AccountFinancialEntry` → `CombinedFinancialEntry`:** the name is code-only, not
   stored, and neither glossary defines "Combined".
6. **Merging `exportAccountFinancialEntry` and `exportCombined`:** you declined the same
   suggestion from cubic earlier. The shared steps already live in
   `inline-document-export.ts` and `allocate-entry-number.ts`; what's left is four calls
   that differ in port and VAT.
7. **`DIRECT` → `PAYMENT_ONLY`:** Direct books the expense with its PDF, not only the
   payment, and the UI already says "Without suppliers". It needs an enum migration.

Items 1–4 are about 5 files, all in code this stack added.

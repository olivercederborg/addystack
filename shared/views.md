# Views

How to show what a reply's fact table can't hold: a report's view, a decision card's
view, or what a Review row points at. It goes in its own block under the table. Pick the
smallest view that makes the point clear, from the content, and none when the table
makes it, after HumanLayer's
[show-me](https://github.com/humanlayer/skills/blob/bba9d13a/plugins/show-me/skills/show-me/SKILL.md):

- **An interface**: its types and one call site.
- **What changes**: a `diff` in the topic's own shape, such as a file tree, a call tree,
  or a schema. Show the whole block when most of it is new.
- **A comparison of items on the same points**: a table. An audit's results, a list of
  IDs, or a status matrix is evidence, so it goes in the fold.
- **An order of steps**: a flow line in a code block, or Mermaid when it branches.
- **How something works**: one real example traced through it, as [trace](#trace) shows.
- **UI**: a screenshot.

Every view uses the same markers: `-` for
removed and `+` for added in a `diff` block, `← note` for a one-line note, and ★ for
the pick.

## Renames and moves

One `-` and `+` pair per file, with paths from the repo root, or from a folder named once
above the block. Past five pairs, show five that cover each kind of move and fold the
rest with a count.

```diff
- apps/web/src/features/bill-pay/components/pay-bill-panel.tsx
+ apps/web/src/features/bill-pay/pay-bill-panel.component.tsx
- apps/web/src/features/bill-pay/payment-submission.handler.ts
+ apps/web/src/features/bill-pay/payment-submission.operation.ts
```

## Interface and usage

The module's interface with its types, then one call site, in one block. A comment on
the first line names where the module lives and what it hides, so the reader sees a
deep module or a domain module at work. For a change, a `diff` of the signature, with
the call site below it.

```diff
  // apps/server/src/accounts/account-server.service.ts: hides Apple's token exchange
  export interface Interface {
    readonly fetch: (request: Request) => Effect.Effect<Response>;
+   readonly revoke: (user: UserId) => Effect.Effect<void, AppleRevocationError>;
  }

  // call site
+ yield* AccountServer.revoke(userId);
```

## Module shape

The tree after the change, as a `diff`, with a note on each changed line.

```diff
  accounts/
-   account-server.ts
+   account-server.service.ts      ← service role
-   account-ids.ts
+   account-ids.utils.ts           ← hashes, so not a pure rule
```

## Typed call stack

The path from an entrypoint to its side effects, one hop per line, with the type the
data has at each hop. Use it for a design, a PR's changed path, or a bug, and mark the
broken or changed hop with `←`. Three limits keep it short:

- Show only the hops that change or explain the point, at most six. A longer path gets
  split, or goes into a design doc.
- Write a type only where it carries information, such as an Effect's error and
  requirement channels. Skip types like `string`.
- On a decision card or a finding, put it in the fold. The surface keeps its lines.

```txt
Better Auth links the Apple account                         (Promise world)
  -> hooks.claimGrants(appleSubject, userId)                  : Promise<void>
  -> AppleGrants.claim(appleSubject, owner)                   : Effect<void, AccountPersistenceError>
  -> callbackRunner(effect)                                   : Promise<void>   ← logs defects only
  -> auth.service.ts:73 .catch(() => undefined)               : void            ← typed failures end here
```

For a change, show the current stack and the proposed one as two blocks, or one `diff`.
For a bug where the types don't matter, drop them and keep the `←` marks.

## Types inline

A snippet with the compiler's inferred types as `^?` comments under the code they
describe, and the runtime result when it differs.

```ts
const runHook = yield* callbackRunner;
//    ^? <A, E>(effect: Effect<A, E>) => Promise<A>
```

## Behavior and flow

Two lines, now and after, with the outcome in bold. Use Mermaid only when the flow
branches or crosses runtimes, such as an app, a Worker, and a Durable Object. Parse
a Mermaid block before it goes on GitHub, as open-pr's `check-body.mjs` does.

> **Now**: Better Auth → own runner → **crash unlogged**
>
> **After**: Better Auth → `callbackRunner` → **crash logged**

## Comparison

A table, when the reader compares items on the same points. Keep it to six rows; past
six, show the rows that make the point and fold the rest with a count. The glance budget
skips a table of up to six rows, since it's a view and not prose.

````markdown
✅ **One of the three export helpers only forwards its call.**

| Finding | The export builds its CSV through three helpers, and `prepareRows` adds nothing. |
|---|---|
| Effect | Inlining `prepareRows` changes no caller. |

| Helper | Called by | Earns its place |
| --- | --- | --- |
| `toRows` | `prepareRows` | yes: filters and formats rows |
| `prepareRows` | `exportTransactionsCsv` | no: forwards to `toRows` |
| `toCsv` | `exportTransactionsCsv` | yes, but its array check can't fail |

---

**Next**

- **`a` → inline `prepareRows`, one commit** · *recommended*
````

## Trace

To explain how something works, follow one real example through each step, with its
value at each step and a `←` on the step that matters.

````markdown
✅ **A receipt reaches the books in three steps; VAT splits in the middle.**

| Example | One €121 receipt, traced below; the bookkeeper sees only its photo. |
|---|---|
| Effect | A receipt with no VAT line books all €121 as expense. |

```txt
upload     receipt.jpg, €121.00 total
  -> parse { net: 100.00, vat: 21.00, rate: 21% }        ← VAT splits here
  -> book  expense 100.00 · input VAT 21.00 · bank −121.00
```
````

## Stack map

The PR stack as a tree, each PR with its CI state and whether it's a draft, after any step
that pushes or restacks.

```text
main
└─ #123 sessions       ✅ CI · draft
   └─ #124 server      ✅ CI · draft
      └─ #126 cleanup  ⏳ CI · draft   ← this branch
```

## Ship gate

A merge go or a push go. The header row is the PR as a link whose text says what it
changes for a user or caller, not its title, then its state, and the `size:` rating
`scripts/github.sh target N` prints, with `leaving out` only when those files outweigh
the rest, and the thread that made it when another did. A push go's header is the branch
and its unpushed commits. Its rows:

- **Risk**: each warning or failure, one row each, the gap behind the `review:` rating
  among them.
- **Proof**: the passing checks and the restack state.
- **Undo**: how to roll it back.

Its view is what the reader accepts, so they can say yes without opening the PR: a
table headed `You accept`, then the PR, or the branch for a push with no PR, with a short
phrase per cell, `none` when empty, and no row that's empty for all:

- **New**: what didn't exist before, such as a command or an index.
- **Changes**: behavior that changes for an agent, a user, or a caller.
- **Edits**: the files, grouped, as in "6 skills name it; 14 synced copies of one line".
- **Goes live**: what runs once it lands, such as a deploy or a setup step, and who
  runs it.
- **Left out**: what it doesn't do that the reader might expect.

````markdown
🟡 **Merge #124, so a retried upload stops creating a second receipt?**

| [#124, A retry reuses its receipt](https://github.com/acme/app/pull/124) | draft · +120 −30 in 4 files |
|---|---|
| Risk | ⚠️ blast-radius not run: it adds a unique index on receipts. |
| Risk | ⚠️ Review 8/10: the timeout path has no test. |
| Proof | verify-work Done at head · CI · tests 41/41 · no restack |
| Undo | Revert #124, then drop the index. |

| You accept | #124 |
| --- | --- |
| New | a unique index on each receipt's upload id |
| Changes | the upload API answers a retry with the first receipt |
| Edits | the upload handler and its test; one migration |
| Goes live | the deploy runs the migration on about 80,000 receipts |
| Left out | a message telling the user their upload was reused |

<details><summary>Idiom sources · review rounds</summary>

Idiom sources: none recorded. Review: two rounds, one finding left open.

</details>

---

**Next**

- **`a` → merge #124** · *recommended*
- `b` → no: keep #124 as a draft
````

A ship gate is a card, not a report, so several PRs, in one repo or across repos, share one fact table: its header row is
`Stack`, then the PRs in merge order, and a Risk names its PR. The view gets a column per
PR in that order, headed by its link and review rating, each Edits led by its size. Past
three PRs, the one view is a table per PR, since columns grow too narrow and row groups
would pass a view's six rows.

````markdown
🟡 **Merge #124 then #125, so a retried upload stops double-booking?**

| Stack | #124 then #125, bottom first · both draft · +180 −42 in 6 files |
|---|---|
| Risk | ⚠️ #124 adds a unique index on receipts, and blast-radius wasn't run. |
| Risk | ⚠️ #124's review is 8/10: the timeout path has no test. |
| Proof | verify-work Done on both at head · CI · no restack |
| Undo | Revert #125, then #124, and drop the index. |

| You accept | [#124, A retry reuses its receipt](https://github.com/acme/app/pull/124) · 8/10 | [#125, Receipts return their upload id](https://github.com/acme/app/pull/125) · 9/10 |
| --- | --- | --- |
| New | a unique index on receipts' upload id | an upload id field on receipts |
| Changes | a retry gets its first receipt back | the receipts API returns each upload id |
| Edits | +120 −30 in 4 files: upload handler, its test, a migration | +60 −12 in 2 files: receipt type, its serializer |
| Goes live | the deploy runs the migration | none |
| Left out | a message that the upload was reused | the app doesn't show the id yet |

---

**Next**

- **`a` → merge #124 and #125** · *recommended*
- `b` → no: keep the stack as drafts
````

The fold lists each PR's idiom sources: the `idiom:` lines `scripts/github.sh target N`
prints for its Done, or "none recorded" for a Done that predates them.

## Choosing between shapes

One bold line per option, the pick first with ★, each followed by the same snippet
written its way. Keep the options out of the fold.

## Decision card example

A full card for a design call, with the card's one view as a `diff`:

````markdown
🟡 **Switch the account service to the shared callback runner?**

Group 1 🟡 · 2 ⬜ · 3 ⬜ · 4 ⬜

| Problem | A crash in the sign-in hooks goes unlogged, so a failed Apple sign-in leaves no trace. |
|---|---|
| Pick | Yes, so every hook crash gets logged in one place. |
| Source | The shared runner every other library callback in the app goes through. |

```diff
  // apps/server/src/accounts/account-server.service.ts: runs Better Auth's hooks
- const runHook = Effect.runPromiseWith(services);
+ const runHook = yield* callbackRunner;
```

<details><summary>Proof, other options, sources → shared runner</summary>

OpenCode and Zed route library callbacks through one helper. Wrapping only this
hook in its own logger was the other option.

</details>

---

**Next**

- **`a` → yes, switch it and show group 2** · *recommended*
- `b` → no, keep it as is and show group 2

<!-- turn {"state":"stop","needs":[{"id":1,"kind":"decide","name":"shared callback runner"}],"options":[{"key":"a","class":"decision","text":"yes, switch it and show group 2"},{"key":"b","class":"decision","text":"no, keep it as is and show group 2"}]} -->
````

## Batch card

The calls `queue show` puts on one card: several of one batch, each without a ⚠️ row,
waiting at once. Its headline asks once, and each item is a numbered bold line naming
its target, then its draft in full, so a yes needs no fold. `a` takes all; "a except 2"
or an edit by number changes one, and each item leaves the queue with that answer. A
merge batch is a stack's ship gate, its option the plain request; the gate takes only a
plain request as a merge's go, so a part of it is typed as one, "merge #12 and #14".

````markdown
🟡 **Post the three review replies on Ana's PRs?**

1. **[#41, Retries reuse their receipt](https://github.com/acme/app/pull/41)**: answer the question
   > The retry keeps the first receipt's id, so the client never sees a second one.
2. **[#42, Receipts return their upload id](https://github.com/acme/app/pull/42)**: re-request the review
3. **[#43, Exports page their rows](https://github.com/acme/app/pull/43)**: approve it

---

**Next**

- **`a` → post all three** · *recommended*
- `b` → post 1 and 2 only

<!-- turn {"state":"stop","needs":[{"id":7,"kind":"review","name":"answer on #41"},{"id":8,"kind":"review","name":"re-request on #42"},{"id":9,"kind":"review","name":"approve #43"}],"options":[{"key":"a","class":"stop:post","text":"post all three"},{"key":"b","class":"stop:post","text":"post 1 and 2 only"}]} -->
````

## Reply kinds

The fact table for the kinds of reply the examples above don't show. Finished work ends
on `**Done**`, and a report with a routine next step is the same table above
`**Next**`, as under [Comparison](#comparison).

**The reader has to do something**: a Do row, with its steps numbered under the table.

````markdown
🔴 **Layer 2 of 3 stopped: the export needs an API key.**

| Problem | The export can't sign in to the bank without a key from its console. |
|---|---|
| Do | Create the key: only the account owner can open the console. |
| Proof | Layer 1 is built and verified. |
| Queued | Layer 3, the settings screen, builds meanwhile. |

1. Open the bank's developer console and choose **API keys**.
2. Create a read-only key named `export`.
3. Paste it into `apps/server/.env` as `BANK_API_KEY`.

---

**Next**

- **`a` → build layer 3 while you create the key** · *recommended*
````

**A message to a person**: the header row is `To`, Cost is what it commits the reader
to, and the draft follows in full. **A production write**: the header row is what runs
and where, Effect counts the rows it touches from real data, and Undo says how they come
back.

**Several things**: an item each, grouped by the thing, findings by severity.

````markdown
🔴 **Not ready: the export leaves out the ticket's currency column.**

**Must fix**

- **Currency column**: rows stop at amount; the ticket's header ends in `currency` · `export.ts:41` → fix
- **Commas in descriptions**: unquoted, so "Rent, January" adds a column · `export.ts:58` → fix

**Cleanups**

- **JSON option**: the ticket never asked for it · `export.ts:12` → fix

<details><summary>Checks: ⚠️ lint not set up · ✅ tests 2/2, but one expects the wrong header</summary>

✅ typecheck · a real run printed `2026-01-31,Rent, January,900.00`.

- `export.ts:41` · verified by that run: three columns, the ticket's header has four · source: the ticket
- `export.ts:58` · verified by that run: "Rent, January" split in two · source: RFC 4180
- `export.ts:12` · verified by reading the ticket: no JSON · source: the ticket
- **Mock-only test**, Cleanup · `export.test.ts:8` → fix · it checks its own mock, never the export · verified by reading the test

</details>

---

**Next**

- **`a` → fix the currency column, quoting, JSON option, and mock test** · *recommended*
````

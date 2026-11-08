# Views

How to show a reply's point: a report's shape, a decision card's view, or a **Review**
item. Pick the smallest view that makes the point clear, from the content, and none when
a sentence makes it, after HumanLayer's
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

Right now the export builds its CSV through three helpers, compared here:

| Helper | Called by | Earns its place |
| --- | --- | --- |
| `toRows` | `prepareRows` | yes: filters and formats rows |
| `prepareRows` | `exportTransactionsCsv` | no: forwards to `toRows` |
| `toCsv` | `exportTransactionsCsv` | yes, but its array check can't fail |

- Inlining `prepareRows` changes no caller.
````

## Trace

To explain how something works, follow one real example through each step, with its
value at each step and a `←` on the step that matters.

````markdown
✅ **A receipt reaches the books in three steps; VAT splits in the middle.**

Right now the bookkeeper sees only the receipt photo, so here's one €121 receipt, traced:

```txt
upload     receipt.jpg, €121.00 total
  -> parse { net: 100.00, vat: 21.00, rate: 21% }        ← VAT splits here
  -> book  expense 100.00 · input VAT 21.00 · bank −121.00
```

- A receipt with no VAT line books all €121 as expense.
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

One line per PR, in merge order, naming what it changes and the thread that made it
when another did, then the passing checks and restack state on one line, each warning
or failure on its own line, and how to roll it back.

```text
#124  uploads: a retry reuses its receipt instead of creating a second
      ✅ verify-work Done · CI · tests 41/41 · no restack
      ⚠️ blast-radius not run: adds a unique index on receipts
      rollback: revert #124, then drop the index
```

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

**Problem**: a crash in the sign-in hooks goes unlogged, so a failed Apple sign-in
leaves no trace.

```diff
  // apps/server/src/accounts/account-server.service.ts: runs Better Auth's hooks
- const runHook = Effect.runPromiseWith(services);
+ const runHook = yield* callbackRunner;
```

**Pick**: yes, so every hook crash gets logged in one place.

**Source**: the shared runner every other library callback in the app goes through

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

## Pages

When Markdown can't show it, such as a highlight on part of a name across many renames,
two trees side by side, or a UI, publish a page. Keep the same markers there: struck through for removed and a green highlight for added.
Check the exact page at 728px and 390px wide before it goes out.

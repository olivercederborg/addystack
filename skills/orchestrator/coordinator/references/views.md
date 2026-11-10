<!-- Copy of shared/views.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Views

Each reply primitive with a real example, then the code shapes a decision or a Before →
after often carries. Compose the primitives the moment needs; none is required except
the headline and the turn block. Every view uses the same markers: `-` for removed and
`+` for added in a `diff` block, `← note` for a one-line note, and ★ for the pick.

## Headline

A status marker, then the outcome in bold, in the reader's terms: what happened or what
they decide, not what you did. ✅ done and nothing needs them, 🟡 a decision or a risk,
🔴 broken or blocked on them, ⏳ still working. A question gets its answer here; a ⏳
headline names what it waits on.

> 🟡 **Close #36? It was meant to save review time, and it saves almost none.**

## Fact table

Labeled rows, `label | value`, right under the headline, when the reader decides. Pick
the labels the call needs, such as Problem, Pick, Source, Risk, Cost, Undo, or Effect;
a value is a sentence the reader can act on without asking what it means.

````markdown
🟡 **Keep the test we used to check the fix-the-cause rule?**

| What | #312 saves the 8 replays built today: 5 past fixes where you pushed back on a quick patch, and 3 safety checks, such as not bundling extras into a hotfix. |
|---|---|
| Pick | Merge it, so the next attempt at the symptom-fix problem is measured the same way. |
| Effect | None on agents: it's a test. |

---

**Next**

- **`a` → merge #312** · *recommended*
````

## You accept

A merge or push go: what the reader accepts, by kind, so they can say yes without
opening a PR. One column per PR in merge order, headed by its link and what it does,
for one PR or several; when columns would be too narrow to read, a table per PR. Use the
kinds this change has, such as New, Changes, Edits (the files, grouped), Goes live (what
runs once it lands, and who runs it), and Left out (what the reader might expect that it
doesn't do), `none` in a cell that's empty. Each risk is a ⚠️ line under it, naming its
PR, and the fold lists the checks and each PR's idiom sources. A line of context first
when the go answers an earlier question.

````markdown
🟡 **Ready to merge: the kit now owns domain-modeling. Merge both?**

This morning you asked whether domain-modeling belongs in the kit. It does. Its upstream author renamed the glossary file to `GLOSSARY.md`, but all five of your repos use `CONTEXT.md`, so agents could look in the wrong file.

| You accept | [addystack#55](https://github.com/acme/addystack/pull/55) the kit | [dotfiles#36](https://github.com/acme/dotfiles/pull/36) your machines |
| --- | --- | --- |
| Changes | in planning, domain-modeling challenges fuzzy terms and records them in `CONTEXT.md`; autonomous runs only read it | none |
| New | the skill, with credit to its author; scope-grill's partial copy goes, and five skills point to it | a setup step that swaps the upstream copy for the kit's |
| Goes live | on merge | I run setup on both machines after merging; the old copy is kept |
| Left out | the same author's other three skills, which carry the same rename risk | none |

⚠️ No second-model review ran on either PR.

<details><summary>Checks: ⚠️ no second-model review · ✅ verify-work Done on both</summary>

Idiom sources: none recorded for either PR.

</details>

---

**Next**

- **`a` → merge addystack#55 and dotfiles#36** · *recommended*
- `b` → run a Codex review first
````

## Comparison

A table, when items differ on the same points: options, results, or picks. An audit's raw
results or a list of IDs is evidence, so it goes in the fold.

````markdown
✅ **You picked text over pictures in both rounds.**

| Situation | Picked | Over |
| --- | --- | --- |
| Merge across two repos | fact table, a column per PR | colleague message, a visual card |
| Waiting on background work | since-you-left log | running table, progress bars |
| "What does this PR do?" | before → after text | a diagram, a story |
````

## Before → after

What a change does, shown concretely: the command, call, screen, or tree before and after,
and its size when the reader weighs it.

````markdown
✅ **#44 closes a way around the merge check.**

Before: `gh pr merge 39 && gh pr merge 41`: your go for #39 also merged #41, unchecked.

After: a command with two merges is denied, and each merge runs on its own.

34 lines in 3 files. The gate tests pass.
````

## List with reasons

Several concrete items, each named, with why: renames, follow-ups, or a code-shape call.
The names go into the Next option too, never a count of them.

```diff
  accounts/
-   account-server.ts
+   account-server.service.ts      ← service role
-   account-ids.ts
+   account-ids.utils.ts           ← hashes, so not a pure rule
```

## Since you left

What changed while the reader was away, oldest first, each line with its time, then
what's running and when it's back. Give a time only when a past run or this run's
progress measures it. Close on what you'll do next.

````markdown
⏳ **Two things are running. Nothing needs you before about 15:30.**

- **13:05** · Merge options that can name the repo: the fix is in, and its tests are being written; back around 14:30.
- **13:20** · The "is this the long-term fix?" check started building, then a replay test; back around 16:00.

Next from me: the merge-option fix, for you to approve.
````

## What changed for you

Work is done: what's different for the reader now, how to undo it, and anything left
for them, in plain sentences.

````markdown
✅ **domain-modeling is live on both machines.**

Agents now load the kit's version, which uses `CONTEXT.md`. The upstream copy is kept in `~/.local/state/agent-skills/replaced/` if you ever want it back. Your Mac's dotfiles are two merges behind, so pull when convenient.

---

**Done**. Nothing else is open.
````

## Project view

"What's going on?" across a project: a heading each for Needs you, Running, and Done (named
for its span, such as Done today, so it isn't read as the closing), one line per item. Needs you comes first, ordered by what unblocks the most, each item sized
by what it takes from the reader, such as a yes or no or a login.

````markdown
🟡 **Two things need you; two are running.**

**Needs you**

- Merge addystack#55 and dotfiles#36, so the kit owns domain-modeling: a yes or no, with what each PR changes.
- Keep #312, the replay test for the fix-the-cause rule: a yes or no; it changes nothing agents do.

**Running**

- Merge options that can name the repo: writing tests, back around 14:30.
- The "is this the long-term fix?" check: building, back around 16:00.

**Done today**

- The reply audit: 4,803 of your messages, with what you picked in both rounds.
````

## Proof

One fold for the checks and sources the reader may audit, its summary leading with the
worst: `<details><summary>Checks: ❌ tests 11/12 · ⚠️ lint not run · ✅ typecheck</summary>`,
then a blank line. A detail worth neither a look nor an audit is cut, not folded.

## Next

`a`, your pick, and `b` only when the reply stops for the reader's call, each naming the
full action and every item in it. Items that don't fit on one line go in a list above.

> `b` → create Linear issues for lenient decoding, V3 re-export, readiness cards, and Dinero

## Turn block

The hidden last line Prefrontal and the hooks read, as the reader's reply rules or the
kit's `references/turn-block.md` define it. Its `needs` name each item as the reply
shows it.

## Decision card example

A full card: the headline asks, the fact table holds the call, the view shows the numbers
behind it, and `a` and `b` answer it.

````markdown
🟡 **Close #36? It was meant to save review time, and it saves almost none.**

| Problem | #36 changes how a third review round labels repeated findings, to save an estimated 150 min a day. |
|---|---|
| Pick | Close it. Long-term, it adds stops for you without saving time. |
| Source | A replay of 120 real findings: today's wording already labels them, so #36 saves about 0 min. |
| If kept | It would leave 6 of 8 repeat bugs for you to decide at merge. |

<details><summary>Proof: the 120-finding replay</summary>

The replay ran today's wording and #36's on the same findings.

</details>

---

**Next**

- **`a` → close #36** · *recommended*
- `b` → keep #36 as a draft

<!-- turn {"state":"stop","needs":[{"id":1,"kind":"decide","name":"close the review-round change"}],"options":[{"key":"a","class":"decision","text":"close #36"},{"key":"b","class":"decision","text":"keep #36 as a draft"}]} -->
````

Some stops carry their own rows. A **message to a person**: `To`, who gets it; Cost, what
it commits the reader to; and the draft in full, in their voice. A **production write**:
what runs and where, the rows it touches counted from real data, and how they come back.

## Code shapes

### Interface and usage

The module's interface with its types, then one call site, in one block. A comment on
the first line names where the module lives and what it hides. For a change, a `diff`
of the signature, with the call site below it.

```diff
  // apps/server/src/accounts/account-server.service.ts: hides Apple's token exchange
  export interface Interface {
    readonly fetch: (request: Request) => Effect.Effect<Response>;
+   readonly revoke: (user: UserId) => Effect.Effect<void, AppleRevocationError>;
  }

  // call site
+ yield* AccountServer.revoke(userId);
```

### Renames and moves

One `-` and `+` pair per file, with paths from the repo root, or from a folder named once
above the block. A long list shows a pair for each kind of move and folds the rest by
name.

```diff
- apps/web/src/features/bill-pay/components/pay-bill-panel.tsx
+ apps/web/src/features/bill-pay/pay-bill-panel.component.tsx
```

### Typed call stack

The path from an entrypoint to its side effects, one hop per line, with the type the
data has where it carries information, such as an Effect's error channel. Show only the
hops that change or explain the point, and mark the broken or changed hop with `←`. On a
decision card or a finding, it goes in the fold.

```txt
Better Auth links the Apple account                         (Promise world)
  -> AppleGrants.claim(appleSubject, owner)                   : Effect<void, AccountPersistenceError>
  -> callbackRunner(effect)                                   : Promise<void>   ← logs defects only
  -> auth.service.ts:73 .catch(() => undefined)               : void            ← typed failures end here
```

### Types inline

A snippet with the compiler's inferred types as `^?` comments under the code they
describe, and the runtime result when it differs.

```ts
const runHook = yield* callbackRunner;
//    ^? <A, E>(effect: Effect<A, E>) => Promise<A>
```

### Behavior and flow

Two lines, now and after, with the outcome in bold. In a PR body, a flow that branches
may be Mermaid; parse it first, as open-pr's `check-body.mjs` does.

> **Now**: Better Auth → own runner → **crash unlogged**
>
> **After**: Better Auth → `callbackRunner` → **crash logged**

### Trace

To explain how something works, follow one real example through each step, with its
value at each step and a `←` on the step that matters.

```txt
upload     receipt.jpg, €121.00 total
  -> parse { net: 100.00, vat: 21.00, rate: 21% }        ← VAT splits here
  -> book  expense 100.00 · input VAT 21.00 · bank −121.00
```

### Stack map

The PR stack as a tree, each PR with its CI state and whether it's a draft, after any step
that pushes or restacks.

```text
main
└─ #123 sessions       ✅ CI · draft
   └─ #124 server      ✅ CI · draft
      └─ #126 cleanup  ⏳ CI · draft   ← this branch
```

### Choosing between shapes

One bold line per option, the pick first with ★, each followed by the same snippet
written its way. Keep the options out of the fold.

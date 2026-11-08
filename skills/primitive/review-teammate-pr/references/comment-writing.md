# Comment style

The author, and often their agent, reads the comment. Both should know what to do
after one read.

- **One concern per comment,** with one bounded request.
- **Match the wording to the user's decision:**
  - **blocking**: what happens, then the fix: "X does Y. Z would fix it."
  - **non-blocking**: prefix `Non-blocking:`, and end on the fix or the test.
    For a defect, start with the exact prefix `Non-blocking:`, then add a separate
    sentence saying the approval waits on its fix. Other non-blocking findings can
    wait for a later PR.
  - **question**: prefix `Question:` and ask it. Only when the code can't show the
    intent, such as a contract a later milestone may need. A question never blocks.
- **Lead with what happens:** the first sentence states, as fact, what a user or caller
  would see, in plain words, before any symbol names. The review verified it, so say it
  the way the user would.
- **Suggest the fix:** offer it as something the author can take, as in "Z would fix
  it" or "a test like … could cover it", the way a colleague suggests.
- **Speak the glossary:** before drafting, read the repo's glossary (the root and the
  touched package's `CONTEXT.md`, or `GLOSSARY.md`). Name each domain concept by its
  term, swap any word from an _Avoid_ line for the term it points to, and keep code
  identifiers for pointing at code.
- **Keep it short:** before any fold, one claim and its fix in at most 40 words. Evidence
  the author needs, such as a repro, a source, or each consequence, goes in a
  `<details>` after the fix.
- **Anchor on the smallest range that shows the concern,** so the problem and the
  requested change are visible together: one line when it carries enough context, or a
  range for a function, test case, schema, or other block. For a move or deletion,
  anchor on the code that should move or go.
- **Add a snippet when the fix would otherwise be ambiguous, or when the comment argues
  for a different pattern** (test style, call shape, structure): show it before and
  after. Keep any example the card already showed.
  - **Fix the cause:** before a fix goes in, name the root cause. Compare a fix at the
    cause, a fix at the symptom, and the library's own analogous API against the repo's
    rules, and show that comparison in the card. When the fix at the cause fits the
    PR's scope, suggest it. When it would grow the PR well past that scope, suggest the
    in-scope fix, or none, and name the root cause as a possible follow-up. Until the
    comparison is done, state the problem with no fix.
  - **Exact replacement of the anchored lines** in one file: a `suggestion` block with
    only the after code, at its real indentation. It replaces every line in the range,
    and GitHub shows it as before and after with an apply button. Name any import or
    nearby edit it can't include.
  - **Otherwise** (a move, a deletion, or several files): a `diff`, or a sketch labeled
    `Target shape`, with real symbols and installed APIs.
- **Suggest a test** when the behavior could silently regress.
- **Keep the scope tight.** Name adjacent work as a follow-up.

## Examples

A reviewer's own comments, from before agents drafted them. Match their length and
directness:

> Should be able to check the `error._tag` instead

> Non-blocking: You should be able to clean this up using `Layer.mock`

> Its only used one place and we lose the typesafety by making this. Would be better to
> just map errors inline using something like `Effect.catchTags`

A blocker with evidence, cut from a 218-word review comment:

> Trashing a bill while the same Company Member edits or pays it can deadlock:
> Postgres aborts one request. Locking the member `FOR NO KEY UPDATE` would fix it;
> `findWithLockEffect` would need a lock-mode option. A trash-versus-edit test could
> cover it.
>
> <details><summary>Repro</summary>
>
> 1. Trash locks the Payable (`move-bill-to-trash.handler.ts:40`).
> 2. Edit or pay-now locks this member `FOR UPDATE` here, then waits for the Payable.
> 3. Trash sets `trashedByMember`. Its foreign-key check needs `FOR KEY SHARE` on the
>    member row, which `FOR UPDATE` blocks.
>
> Two psql sessions on Postgres 17 reproduce it with `deadlock detected`, and pass with
> `FOR NO KEY UPDATE`. The edit-versus-payment test is a model for the new one.
>
> </details>

---
name: reply-shape
description: Replies the reader takes in at a glance - a one-line headline, the smallest view that makes the point, up to three notes, and the next step - plus a decision card, with the problem, the pick, and its source, when a call needs their judgement. A SessionStart hook loads it in the user's sessions; run /reply-shape to turn it on elsewhere.
disable-model-invocation: true
metadata:
  layer: optional
---

# Reply shape

The reader runs many agents at once and gives each reply a glance. Spend that glance
where their judgement matters: a reply that stops for their call is a
[decision card](#decision-card), and every other reply is a report, written as the
glance below. The work's process stays with you, and its evidence and the other options
go in one fold. Hold to this until the reader says "normal replies".

## The glance

Four parts, in this order. Skip a part that has nothing to say.

1. **Headline**: one line of at most 12 words, a marker and then the outcome in bold, in
   the reader's terms: `✅ **Exports no longer time out.**`, not "added an index on
   `created_at`". The marker says before a word whether the reader is needed: ✅ done
   and nothing needs them, 🟡 a decision or a risk, 🔴 broken or blocked on them, ⏳
   still working. An answer to a question is the headline: your pick for a which or
   whether, or a best guess in concrete units and how sure you are. A ⏳ headline names
   what it waits on and how long it has run, and time left only when a past run or this
   run's progress measures it.
2. **Shape**: the smallest view that makes the point, picked from the content: a
   module's interface with one call site, a diff in the topic's own shape, a table
   comparing items, a flow line for an order of steps, one real example traced through
   to show how it works, or a screenshot for UI, as [views](references/views.md) shows.
   Lead in with one plain sentence that says where things stand and ends in a colon
   naming the view. Write a text view as a code block of at most 15 lines or a table of
   at most six rows. None when a sentence makes the point. A second view only when a
   second point needs its own, beside its note.
3. **Notes**: up to three bullets of at most 15 words each, ranked: an architectural or
   strategic call you made and its reason, a risk, how to see the change, or what only
   the reader can do. A note for the reader opens with its label, as in
   `- **Decide**: …`.
4. **Closing**: below a `---` line with a blank line on each side. At a stop, a fork, or
   an answer, the next step, in the reader's own format when their instructions define
   one. When the work is finished, `**Done**` and one line naming what's still open;
   when only the reader's merge go is left, the reply is a ship gate card instead. When
   only background work is left, the reply is the ⏳ headline and one `then: …` clause
   naming what you'll do when it lands, with no notes: "⏳ **CI on #12, 6 min
   in**, then: fix any failure".

**Budget**: the prose above the fold stays under 60 words; a view, such as code or a
short table, and its lead-in aren't prose. A mid-turn progress message is one line.

````markdown
✅ **Exports no longer time out on big companies.**

Exports used to load every row at once; `Export` now pages them:

```ts
// packages/domain/export/export.ts: paging and CSV encoding stay inside
export const run: (range: DateRange) => Effect<Csv, ExportError>

// apps/web/routes/export.tsx, the one caller, unchanged
const csv = yield* Export.run(range)
```

- Paged inside `Export`, so its callers don't change.
- Risk: a year of rows still takes about 40 s.
````

## Reader items

- **Decide**: a choice only the reader can make. It gets a decision card, and a choice
  queued behind it is one line naming it and your pick.
- **Review**: what goes out or ships on the reader's yes, such as a draft, a push, or a
  UI, gets a decision card. What only waits on their look, such as a PR open for their
  review, is one line.
- **Do**: a login, a device step, or a payment, with why you can't do it, and its steps
  numbered in the reply. Show it once, in the reply that first needs it.

## The fold

At most one fold, for what the reader may audit or compare: checks, sources, the other
options or finding cards, a draft's long diff, and a multi-item run's table of items
with `#`, item, status, and commit columns. Write it as `<details><summary>…</summary>`
and a blank line. The summary leads with the worst check:
`Checks: ❌ tests 11/12 · ⚠️ lint not run · ✅ typecheck`.
Decisions, risks, and the reader's steps stay on the surface. A detail worth neither a
glance nor an audit is cut, not folded.

## Decision card

When a reply stops for the reader's judgement, the card is the whole reply. One call
per reply; queue the rest. A skill that names its own format for a call keeps it, such
as a review's findings with their drafts, or a planning round's questions.

1. **Headline**: `🟡 **<a question answerable yes or no>**`. In a round of several, a
   strip follows it: `Group 1 🟡 · 2 ⬜ · 3 ⬜`.
2. **Problem**: one plain line on what's wrong or at stake, and for whom. The reader
   judges the call against it.
3. **One view**, by the kind of call:
   - **Design**: the pick's interface, data shape, or diff, with a call site, as
     [views](references/views.md) shows.
   - **Product**: what the customer sees, and how many it reaches, counted from real
     data.
   - **Message** to a person: the draft in full, in the reader's own voice, under a
     `**To**: … · **Promises**: …` line naming who gets it and what it commits them to.
   - **Ship gate**, a push or merge: each PR as [views](references/views.md#ship-gate)
     shows.
   - **UI**: the screenshot or recording, and the one thing to judge.
   - **Stuck**, a check still failing after two fixes: each fix and why it failed, and
     the assumption the premise test checked.
4. **Pick**, on a call that weighs options: your answer and what it optimizes, one
   line. **Source**: what it follows. **Cost**, only
   when the pick is hard to undo: a migration, a public API, or a message sent.
5. **One fold** for the proof, the other options, and the sources.

The next step's options are the answers: `a` is yes, your pick, and `b` is no, the
smallest option, often leaving things as they are.
[Views](references/views.md#decision-card-example) shows a full card.

## Writing

- **The reader's words**: short sentences, one idea each, in the reader's terms, such as
  PR, stack, or service. Name anything else by what it does; a label you coined, a hash,
  or a flag goes in the fold. A number says what it means, "about 30% less memory", not
  a raw score, in a table too. Inline code only for a name the reader would type or
  search.
- **Names, not numbers**: call each item by its short name. Number only a list in this
  reply the reader might answer by number, such as findings.
- **Say it once** per session: each piece of code, draft, and warning. A reply whose
  next step posts or sends drafts shows each in full again, since what the reader
  approves is what goes out.
- **One picture** per turn at most: an image or an inline page. Text views, such as
  code, a table, or a flow line, don't count. An inline page (`html_render`) only for
  screenshots, a chart, or a UI mockup; read [pictures](references/pictures.md) first.
- **Tangents wait**: a side issue becomes a later next-step option.
- **Blank lines**: chat joins lines that have no blank line between them, so separate
  lines with a blank line or make them list items.

## Before sending

Read only the headline, the shape, and the notes. They alone must say what happened,
what it means for the reader, and what comes next, with no "what's X?" left. On a
card, read only what's above the fold: the reader must be able to answer yes or no from
it. Cut each sentence that doesn't change that.

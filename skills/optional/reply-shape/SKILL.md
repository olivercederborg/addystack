---
name: reply-shape
description: Replies the reader takes in at a glance - a one-line headline, a fact table or bold item lines, and the next step - plus a decision card, with the problem, the pick, and its source, when a call needs their judgement. A SessionStart hook loads it in the user's sessions; run /reply-shape to turn it on elsewhere.
disable-model-invocation: true
metadata:
  layer: optional
---

# Reply shape

The reader runs many agents at once and gives each reply a glance. Spend that glance
where their judgement matters: a reply that stops for their call is a
[decision card](#decision-card), and every other reply is a report, both written as
the glance below, in plain Markdown. The work's process stays with you. Hold to this until the reader says "normal replies".

## The glance

1. **Headline**: one line of at most 12 words, a marker and then the outcome in bold, in
   the reader's terms: `✅ **Exports no longer time out.**`, not "added an index on
   `created_at`". The marker says before a word whether the reader is needed: ✅ done
   and nothing needs them, 🟡 a decision or a risk, 🔴 broken or blocked on them, ⏳
   still working. An answer to a question is the headline: your pick for a which or
   whether, or a best guess in concrete units and how sure you are. A ⏳ headline names
   what it waits on and how long it has run, and time left only when a past run or this
   run's progress measures it.
2. **Fact table** for one subject, such as a PR or a check: two columns, right under
   the headline. A one-sentence reply has none. A report on several things gets
   **items** instead: a list item per PR, finding, option, or running job, its name in
   bold and a clause of at most 12 words, details under it or in the fold. Group by
   the thing, and findings by severity under a bold **Must fix**, then **Cleanups**.
   - **Header row**: the subject: a PR as a link naming its change, then its state and
     size; or one word, such as Problem or Change, then the point.
   - **Rows**: at most five, each `label | value`. Every value, the header's too, is at
     most 20 words. The label is one word from this list: Risk, what could go wrong;
     Unsure, what you couldn't check; Why, the cause or your reason; Effect, what
     changes, measured; Proof, passed checks or how to see it; Undo, the rollback;
     Skipped, what you left out; Queued, what waits; a decision's Pick, Source, and
     Cost; and the [reader items](#reader-items) Decide, Review, and Do. Risk and
     Unsure rows come first, their value starting with ⚠️.
3. **View**: only what the table can't hold, in its own block under it: code or a diff
   of at most 15 lines, a comparison table of at most six rows, a message draft, the
   reader's numbered steps, or a screenshot. [Views](references/views.md) shows each,
   and a reply of each kind.
4. **Closing**: below a `---` line with a blank line on each side. At a stop, a fork, or
   an answer, the next step, in the reader's own format when their instructions define
   one. When the work is finished, `**Done**` and one line naming what's still open;
   when only the reader's merge go is left, the reply is a ship gate instead. When only
   background work is left, the reply is the ⏳ headline, an item per job if several, and
   one `then: …` clause, what you'll do when it lands, with no table:
   "⏳ **CI on paged exports, 6 min in**, then: fix any failure".

**Budget**: a fact that fits no row or view goes in the fold, and any other prose above
it stays under 60 words. A mid-turn progress message is one line.

````markdown
✅ **Exports no longer time out on big companies.**

| [#212, Exports page their rows](https://github.com/acme/app/pull/212) | draft · +86 −40 in 3 files |
|---|---|
| Risk | ⚠️ A year of rows still takes about 40 s. |
| Why | Paging sits inside `Export`, so its callers don't change. |
| Proof | Tests 41/41 · a 90,000-row export finished in 38 s. |

---

**Done**. Still open: the 40 s yearly export.
````

## Reader items

A skill's Decide, Review, or Do note is a row, or a line under its item.

- **Decide**: a choice only the reader can make. It gets a decision card, and a choice
  queued behind it is a Decide row naming it and your pick.
- **Review**: what goes out or ships on the reader's yes, such as a draft, a push, or a
  UI, gets a decision card. What only waits on their look, such as a PR open for their
  review, is one row.
- **Do**: a login, a device step, or a payment, with why you can't do it, and its steps
  numbered below. Show it once, in the reply that first needs it.

## The fold

At most one fold, for what the reader may audit or compare: checks, sources, the other
options or finding cards, a draft's long diff, and a multi-item run's table of items
with `#`, item, status, and commit columns. Write it as `<details><summary>…</summary>`
and a blank line. The summary leads with the worst check:
`Checks: ❌ tests 11/12 · ⚠️ lint not run · ✅ typecheck`.
Risks and reader items stay in sight. A detail worth neither a
glance nor an audit is cut, not folded.

## Decision card

When a reply stops for the reader's judgement, the card is the whole reply. One call
per reply; queue the rest. A skill that names its own format for a call keeps it, such
as a review's findings with their drafts, or a planning round's questions.

1. **Headline**: `🟡 **<a question answerable yes or no>**`. In a round of several, a
   strip follows it: `Group 1 🟡 · 2 ⬜ · 3 ⬜`.
2. **Fact table**: the header row is `Problem`, then one plain line on what's wrong or
   at stake, and for whom. A call that weighs options adds Pick, your answer and its
   long-term reason; Source, what it follows; and Cost only when the pick is hard to undo: a
   migration, a public API, or a message sent.
3. **One view** under it, by the kind of call:
   - **Design**: the pick's interface, data shape, or diff, with a call site.
   - **Product**: what the customer sees, and how many it reaches, counted from real
     data.
   - **Message** to a person: the header row is `To`, then who gets it; Cost is what it
     commits the reader to; the draft follows in full, in their own voice.
   - **Ship gate**, a push or merge: the header row is the PR or the stack in merge
     order, and the view is what the reader accepts, by kind, a column per PR, or a
     table each past three, as [views](references/views.md#ship-gate) shows.
   - **UI**: the screenshot or recording, and the one thing to judge as a Review row.
   - **Stuck**, a check still failing after two fixes: each fix and why it failed, and
     the assumption the premise test checked as Why.

The next step's options are the answers: `a` is yes, your pick, and `b` is no, the
smallest option, often leaving things as they are.
[Views](references/views.md#decision-card-example) shows a full card.

## Writing

- **The reader's words**: short sentences, one idea each, in the reader's terms, such as
  PR, stack, or service. Name anything else by what it does; a label you coined, a hash,
  or a flag goes in the fold. A number says what it means, "about 30% less memory", not
  a raw score, in a table too. Inline code only for a name the reader would type or
  search.
- **Names, not numbers**: call each item by its short name; number only a list the
  reader might answer by number.
- **Links that name**: cite a PR or issue id as a link whose text names it, as in
  `[DEV-3127, Allow failure-only export emails](…)`, once a reply.
- **Say it once** per session: each piece of code, draft, and warning. A reply whose
  next step posts or sends drafts shows each in full again: the reader approves what goes out.
- **One picture** a turn, only for UI, a chart, or when asked; read
  [pictures](references/pictures.md) first.
- **Tangents wait**: a side issue becomes a later next-step option.
- **Blank lines**: chat joins adjacent lines; separate them with a blank line or a list.

## Before sending

Read only the headline and the table or items. They alone must say what happened, what it means
for the reader, and what comes next, with no "what's X?" left; on a card, the reader
must be able to answer yes or no from them. Cut each row that doesn't change that.

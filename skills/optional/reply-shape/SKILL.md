---
name: reply-shape
description: Replies composed from primitives the moment calls for - a headline, labeled rows for a decision, what each PR asks the reader to accept, before → after, what changed since they left, a project view, and Next options that name the full action - so the reader sees what's going on and what they're accepting without asking "what is X?". A SessionStart hook loads it in the user's sessions; run /reply-shape to turn it on elsewhere.
disable-model-invocation: true
metadata:
  layer: optional
---

# Reply shape

The reader runs many threads at once and reads each reply cold. Build every reply from
one question: **what does the reader need, right now, to understand what's going on and
act?** Pick the [primitives](#primitives) that answer it and put them in the order that
tells the story. Hold to this until the reader says "normal replies".

## Habits

- **Show, don't point.** Whenever you name a PR, a follow-up, a task, or a count, say what
  it is in the same breath: "#312, the replay test for the fix-the-cause rule"; "lenient
  decoding, V3 re-export, and readiness cards", not "the 3 follow-ups". What lives in an
  earlier reply, a fold, or the turn block is out of the reader's sight.
- **Frame it around the reader**: what changes for them, what they're accepting, what
  they need to do. Use their words, short sentences, one idea each. A label you coined
  (R104, "arm", "ship gate") stays with you; name the thing by what it does. A number
  says what it means: "about 30% less memory", not a raw score. Inline code only for a
  name the reader would type or search.
- **Let the moment set the length.** A merge of a big change gets the full picture, a
  status gets a line per running thing, and a yes or no gets one sentence. No word or row
  counts: cut a line only when the reader would act the same without it. Say each piece
  of code, draft, and warning once a session, except a draft the next step sends, which
  shows in full again.
- **Restate context** in one line when they may have lost the thread: after a long wait,
  on earlier work, or on another thread's result.
- **Judge.** On a call, give your pick and its long-term reason.
- **Text, not pictures.** Structure comes from labeled rows, lists, and small tables. A
  picture only when the reader asks for one, or a screenshot of UI; read
  [pictures](references/pictures.md) first.
- **Fold only proof.** What the reader needs to decide stays in sight.
- **Blank lines**: chat joins lines that have no blank line between them, so separate
  lines with a blank line or make them list items.

## Primitives

Each is a building block with one job. [Views](references/views.md) shows each with a real
example, plus the code shapes (an interface, a module tree, a call path) that Before →
after and a decision often carry.

| Primitive | Its job | Use when |
|---|---|---|
| **Headline** | A marker, then the outcome in bold: ✅ done, 🟡 a decision or a risk, 🔴 broken or blocked on the reader, ⏳ still working. On a question, the answer. | Always |
| **Fact table** | Labeled rows, `label \| value`, such as Problem, Pick, Source, Risk, Cost, Undo | A decision |
| **You accept** | What changes, by kind, a column per PR | A merge or push go, for one PR or several |
| **Comparison** | A table across the same few points | Options or results that differ the same way |
| **Before → after** | The change, concretely: a command, a call, a screen, a tree | Explaining what a change does |
| **List with reasons** | Each item named, with why | Several concrete items: renames, follow-ups, a code-shape call |
| **Since you left** | Timestamped changes, what's running, and when it's back | The reader is catching up or waiting |
| **What changed for you** | The effects on the reader, the undo, their move | Work is done |
| **Project view** | Needs you (ordered, each sized), Running, Done | "What's going on?" across a project |
| **Proof** | Checks and sources in one fold, its summary leading with the worst | There's evidence |
| **Next** | `a`, and `b` on a call, each naming the full action | The reply stops for the reader |
| **Turn block** | Hidden state for Prefrontal and the hooks | Always |

Common compositions:

- **Decision card**: a yes-or-no Headline, a Fact table with Problem, Pick, and Source,
  the one view the call needs (Before → after, a Comparison, the interface, or a message
  draft in full), Proof, and Next with `a` yes, your pick, and `b` no, the smallest
  option. One call per card; queue the rest. A skill that names its own format for a
  call, such as a review's findings or a planning round, keeps it.
- **Ship gate**: Headline, You accept, each risk as a ⚠️ line, Proof, and Next.
- **Status**: Headline and Since you left. **Done**: Headline and What changed for you.
- **A Do**, something only the reader can do (a login, a device step, a payment): why
  you can't, then numbered steps, shown once, in the reply that first needs it.

## Contracts

Machines read these, so they hold whatever the moment:

- **Closing**: below a `---` line with a blank line on each side. At a stop, a fork, or
  an answer, `**Next**` in the reader's own format when their instructions define one.
  When the work is finished, `**Done**` and what's still open. When only background work
  is left, the ⏳ headline and one `then: …` clause naming what you'll do when it lands.
- **Next options** name the full action and every item in it. A merge option's text is
  the plain request with no other step, "merge #12 and #13", since merge-gate takes
  only that as the reader's go; `hooks/reply_budget.py` sends back any other.
- **Numbers on action lines**: a Next, Needs you, or Done line that cites one ("item
  48", "fix 21–33") gives its name beside it; `hooks/bare_references.py` sends back one
  that doesn't.
- **Turn block**: every final reply ends with one, as the reader's reply rules (Turn block
  section) or the kit's `references/turn-block.md` define it; `hooks/routine_stop.py`
  sends back one that's missing or malformed.

---
name: scope-grill
description: "Grills a plan on only the decisions that matter, ending with a \"Not in scope\" list. Use for a brain-dumped feature or idea, a request to be grilled or to \"plan it out\", or scoping a spec, ticket, or PR."
metadata:
  layer: primitive
---

# Scope grill

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Decide a plan with every decision's scope cost in the open, so the cost is chosen, not
discovered.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Item kind here: **Decide**, one per question, as the round's lines.

## 1. Set the scope line

Before asking anything, read the request, the linked issue, the code involved, the
domain docs (the area's `CONTEXT.md` and ADRs), and any spec, ticket, or PR you start
from, with a PR's diff against its base. A brain dump (loose thoughts in any order) is a
fine request: draw the goal, the must-haves, and the open questions out of it.

Take the Bar from the request, or ask whether the smallest working pilot or lasting
work is wanted. Building holds the must-haves. At a pilot Bar the smallest option that
meets the goal wins; at lasting work the design that holds up as it grows wins. Play
the goal back in the user's words. Show the plan and questions in the first round. Keep
the user's boundaries verbatim: on the plan, or copied into the fold and named on the
plan when the glance can't hold them.

**Milestones**: when the request holds more than one step that ships on its own, map
them first, in order, each with its goal and size, in the fold.
Grill only the next one in full. The others stay on the map with their scope, not under
Not in scope, so a later run picks it up.

## 2. Ask only the questions that matter

- **Decisions that change the code only: what, not how.** Ask only what changes what
  gets built: behavior, must-haves, scope, and order. Park everything else in **Not in
  scope**, one line each, and a question about how modules are shaped, named, or call
  each other on a **For architect** list, with the decision it depends on, such as how
  a job is registered or wired in. Name the file or module it concerns. When the goal
  is a restructure or rename, the target module list and what goes where are the
  *what*: ask them as a round-1 question.
- **Skip the obvious.** When a question's options add no scope, are easy to undo, and
  have a clear recommendation, mark it pending in **Assuming** instead of asking. If it adds work, propose it instead.
- **Question creep is scope creep.** When a question exists only because an earlier
  answer widened the scope, say so.
- **Work the design tree.** A round asks only the **frontier**: decisions whose
  prerequisites are settled. Recompute it after each answer.
- **Rounds** have one to three open frontier questions, highest impact first. Ask only
  decisions that need the user's input; don't add a question to fill the round. Each has
  a recommended option, and one answer can settle the round: every pick, or every pick
  but the ones it overrides by number.
- **Facts are yours; decisions are the user's.** Look up what the code, config, or
  tools can answer, using sub-agents in parallel if needed. While a lookup runs, only
  the questions that depend on it wait.

## 3. Show each option's impact

Every reply in the grill, including a clarification, uses this order. Aim for about 45
words of prose above its fold; the Stop check sends a round back at 60. Plan items and
the fold's summary count, while code and diff blocks and the fixed labels (these
headings, their tags, `Size`, `Pick`, `(say if wrong)` and the who-agreed tags) don't.
Only **Proposed this round** and **Changed this round** are `diff` blocks; the plan is plain bullet lists,
outside any code fence. When it doesn't fit, shorten its clauses and fold the rest by
name, such as `+4 more in the fold`:

1. A short headline. **Proposed this round** · *my suggestion, not agreed*, word for word: a
   `diff` block with `+` lines for every suggested addition, including assumptions
   that add work and wider recommendations. Place it above the plan; move an addition
   to Building only after acceptance.
2. **Changed this round**: a red/green `diff` only if something changed since the last
   round. Round 1 is all green, including your own baseline reading. A Size change goes
   on the plan's Size line, not here.
3. Print **The plan so far** as its own heading every time, then these plain headings
   in order: **Building** · **Not building** · **Assuming** (say if wrong) · **Size**.
   Show the complete Size on its line, including PRs, files and migrations; use
   `Size`, not a synonym, so the Stop check can read it. Mark each Building
   clause `(you)`, `(you, round N)`, or `(me, round N)`; write the heading exactly as
   **Assuming** (say if wrong), with each value on its heading line as in the example.
   Keep about five Building clauses,
   folding older ones by name. Assumptions stay `pending` until checked. Size is PRs ·
   ~files · migrations · `lines not estimated` unless measured. Show a change once, as
   a trail on that line, such as `~4 → ~6 files` or `0 → 1 → 0 migrations`. Start a
   trail only from a known count; otherwise write `1 proposed migration`.
4. **Pick**: number each question and its recommended answer and impact. The fold holds
   context, options, costs, sources, and the **For architect** list, or `none`. Then wait: the user takes every pick, names an
   alternative, or overrides a question by its number.
   A user's `confirm` takes the offered picks, unless they say otherwise.

Example, when a table is suggested but not agreed:

````markdown
🟡 **Keep serviceData?**

**Proposed this round** · *my suggestion, not agreed*

```diff
+ A per-currency accounts table
+ Size: 0 → 1 migration
```

**The plan so far**

- **Building**: per-currency account picker (you)
- **Not building**: account creation
- **Assuming** (say if wrong): old exports keep accounts (pending)
- **Size**: 2 PRs · ~20 files · 0 migrations · lines not estimated

**Pick**: serviceData, no migration.

<details><summary>⚠️ 1 unchecked · costs</summary>

Not checked: whether old exports keep their account; no export history is available.
**Source**: `docs/exports.md`, one account per export.
**For architect**: none.
…

</details>
````

Add a decision diagram only when the choice hinges on a fact that's easier to see as a
branch. When `html_render` exists and a round changes what a user sees (a layout, a
state, or a flow between screens), through an option or an assumed default, its picture
is one mockup page: prototypes of the real screens, built as
[mockups](references/mockups.md) says. A round that changes no screen gets none. For
each option, show:

- **Change**: what the option touches, named in its size, such as `1 file: export.ts`.
  Add a small `diff` of observable behavior only when names don't show it, and fold a
  longer one. Draw moves per [views](references/views.md). It shows scope, not design: code
  shape is `architect`'s call.
- **Cost line**: after the option's name, Scope · Size · Undo, such as
  `Adds a repository method · ≈3 files · hard to undo: migration`. Use the exact
  scope labels below for each option, even when its details are shared.
  - **Scope**: `No extra scope`, `Drops <what>`, or `Adds <what>`. Adds covers a new
    concept, module, config, migration, public API, test surface, or a seam with only
    one real implementation. A seam is real when two implementations need it now. Use
    `codebase-design` for seam questions when it's installed.
  - **Size**: files touched, counted from a codebase search. Mark estimates with `≈`.
    When the code doesn't exist yet, estimate from what the option adds, such as
    `≈3 new files`; always give a count, never `unknown`.
  - **Undo**: `easy to undo`, or `hard to undo: <why>`, such as a migration or a
    public API.
- **ADR conflicts**: flag any option that contradicts an existing ADR.

- **The recommendation** is the option that best meets the must-haves at the **Bar**.
  Ground it with [grounding](references/grounding.md), with its evidence lines in
  the fold. Also ground a losing option when its idiom decides the question.
- **"Becomes worth it when"**: the goal's right shape wins, with what it adds, unless
  slim-scope says it waits. Any other losing wider option names the signal that would
  justify it later, and moves to **Not in scope**. Every narrower option that
  loses names the concrete work it would cost to widen later, even when the narrower
  choice is easy to undo. With one losing option, the Pick line can carry it.
- **Domain docs as you go**: use `domain-modeling` when an answer settles a domain term,
  the user's word is fuzzy or conflicts with the glossary, or a decision may need an ADR.
  Show a settled term in that question's fold and write it once the round is accepted;
  offer an ADR as an option in that turn.

## 4. Watch the whole plan

- **A wider pick** changes the plan and Size trail in the next round and shows any new
  questions it creates.
- **A second PR**: when the size passes what one reviewable PR can hold, say so and
  propose a split into vertical slices, each shipping a working part of the outcome. A
  wide rename or contract change goes expand → migrate → contract.
- **A removed premise**: when a decision removes the reason behind an earlier pick, such
  as a tool that makes a feared conflict cheap, reopen that pick in the next round.
- **Challenges**: "are you sure?" asks for a re-check. Change a recommendation only on
  new evidence, and name that evidence.

## 5. Cross-review the plan

When the frontier is empty, first check each decision against the **Lenses**, and
against the vendor's docs for any third-party API it uses. A conflict reopens that
question as a new round. Then have the other model (Codex from Claude, Claude from
Codex) review the plan as a T3 child task on the **Reviewers** target in
[t3-delegation](references/t3-delegation.md), with the prompt below as `task`,
`role: "review"`, `interactionMode: "plan"`, and `mode: "wait"`.

```text
Review this plan before it is built. Read-only: do not edit, commit, push, or comment.
Goal: <goal>
Decisions: <one line each>
Not in scope: <list>
Report only gaps that would make the build wrong or incomplete, risks with a concrete
failure, and a simpler option that meets the same goal, each with file:line evidence.
If there are none, say so.
```

Verify each point with [grounding](references/grounding.md). A point that holds and
changes a decision reopens it the same way; the rest go in the summary. If the reviewer
fails (auth or timeout), say so and continue.

## 6. Summary

When the cross-review is settled, finish with:

- **Decisions**: one line each, numbered `D1.`, with its cost line. One the user
  didn't pick, such as an Assuming item or one of My additions, ends `[assumed]`.
- **Resulting shape**: one combined `diff` of the file tree the plan touches.
- **For architect**: the structure questions parked for `architect`, or none.
- **Scope and size**: the Size trail and each widening with the answer that caused it.
- **Not in scope**: the parked questions, the losing options, and the baseline's
  exclusions, in the format below.
- **Milestones**: the map, with the one this plan covers marked, or none.
- **Checks**: one observable behavior per must-have that the build can prove with a
  test or the project's `verify-<app>` skill, such as "the March export has 12 rows".
  The build is done when every check passes.
- **Test seams**: where the tests hook in. Use the highest seam that covers the
  behavior, ideally one.
- **Docs**: `+N terms · N ADRs` written, or none.
- **Cross-review**: `N points · N reopened · N dropped`, with one line for each point
  kept, or `clean`.

Use the same round format at plan-ready. List **My additions**: every addition
agreed by default, not picked by the user, including docs, tests and migrations. The user's approval accepts them and saves the
plan, or they drop them.
The fold holds the exact text to save, copied verbatim from any draft the session
already wrote, with every artifact that draft carries, such as an email. Its target is
the repo's issue tracker (one issue per
milestone, a sub-issue per PR), or a Markdown file in the repo's plans folder when it
has no tracker. The saved plan holds the goal, bar, decisions, checks, For architect,
Not in scope and milestone map. Write nothing before approval. If saving issues wasn't
requested this session, approval continues without saving, and dropping the additions
stays open; ask for issue creation separately.

After approval, continue to `architect` when decisions add or reshape a module's
interface or For architect isn't empty; otherwise continue to the next step the router
picks, or `build` when the user wants to drive each step.

**Done when:** no decision is left silently assumed, the user explicitly chose every
widening, the other model's review is settled, every must-have has a check, the Not in
scope list holds everything left out, and the plan is saved or the user chose not to.

## Not in scope

Each item gets one line: what is out, why the goal doesn't need it, and the signal that
would bring it back.

```markdown
## Not in scope

- **JSON export**: the request is CSV only. Revisit when a consumer needs JSON.
- **Per-company time zones**: transaction dates carry no time. Revisit when dates
  include times or month boundaries are reported wrong.
```

To add it to a spec, ticket, or PR, show the exact section and its target, and on
approval replace or add only that artifact's Not in scope section, then link the result
once it shows.

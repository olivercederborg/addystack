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

Item kind here: **Decide**: each ❓ question is one, in place of a decision card.

## 1. Set the scope line

Before asking anything, read the request, the linked issue, the code involved, the
domain docs (the area's `CONTEXT.md` and ADRs), and any spec, ticket, or PR you start
from, with a PR's diff against its base. A brain dump (loose thoughts in any order) is a
fine request: draw the goal, the must-haves, and the open questions out of it.

Take the Bar from the request, or ask whether the smallest working pilot or lasting
work is wanted. The plan builds the must-haves. At a pilot Bar the smallest option that
meets the goal wins; at lasting work the design that holds up as it grows wins. Play
the goal back in the user's words in the fold. Keep the user's boundaries verbatim: on
the plan, or copied into the fold and named on the plan when the glance can't hold them.

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
  have a clear recommendation, list it under `Assuming (say if wrong):` instead of asking. If it adds work, make it a *My suggestion:* item instead.
- **Question creep is scope creep.** When a question exists only because an earlier
  answer widened the scope, say so.
- **Work the design tree.** A round asks only the **frontier**: decisions whose
  prerequisites are settled. Recompute it after each answer.
- **Rounds** have one to three open frontier questions, the one whose options differ
  most in size first. Ask only decisions that need the user's input; don't add a
  question to fill the round.
- **Facts are yours; decisions are the user's.** Look up what the code, config, or
  tools can answer, with parallel sub-agents when two or more lookups are independent.
  While a lookup runs, only the questions that depend on it wait.

## 3. Ask the round

Every grill reply, a clarification too, is a round in this order, as plain
text. Aim for about 150 words above the fold, as in the example, and fold the rest by
name, such as `+4 more in the fold`:

1. **Headline**: `🟡 **Round N: <what this round decides>?**`, then question 1, with only a
   mockup page between them. A fact a question rests on goes in its sentence or the fold.
2. **Questions**, one to three, a blank line between them. Each is `❓ **N · <question>?**`,
   worded so "yes" takes the recommendation, then one sentence naming the other option
   and its cost. Under it, the recommendation alone on a `➡️` line, with its reason and
   size in files.
3. **The plan, once**: `**Plan** · <PRs> · ~<files> · <migrations>`. A change from the
   last size the user saw, in this session or the request, shows as a trail on that
   line, such as `1 → 3 PRs`; start a trail only from a known count,
   otherwise write `1 proposed migration`. Then plain bullets, a sentence each: what
   gets built; *My suggestion:* before each item the user hasn't agreed to, such as a
   wider behavior, an added check or dependency, or a PR split, until they accept it;
   `Not building:`; and `Assuming (say if wrong):`. A bullet this round changed can lead
   with `New:`, and a dropped item shows once as `Dropped: …`. Past about five built
   items, fold the older ones by name.
4. **The fold**: each option with its change and cost line, the sources, any unchecked
   fact, and the **For architect** list, or `none`.
5. **Wait.** In the reply's Next, `a` takes every ➡️ answer, and the user overrides one
   by number, such as `2: shared`. A user's `confirm` takes them too.

Example:

````markdown
🟡 **Round 1: how much should the loading screens reuse existing skeletons?**

❓ **1 · Dashboard: reuse its five section skeletons?** The other option is one new
skeleton, kept in step with the sections by hand.

➡️ Yes: export and compose them, about 6 files. They can't drift.

❓ **2 · Settings, members, top-ups, profile: an inline skeleton in each loading file?**
The other option is shared components, about 8 files with one user each.

➡️ Yes, as exports and archive already do, in 4 files.

**Plan** · 1 PR · ~11 files · no migrations

- Loading screens on six pages, covering only the page body. Headers and tabs stay real.
- Transactions reuses its table-row and filter skeletons.
- *My suggestion:* prove it with a production build and a slow server.
- Not building: connections, export tabs, Cache Components.
- Assuming (say if wrong): prefetching is fine, since each loading screen stays cached
  for 5 minutes.

<details><summary>Options, costs, sources</summary>

**1 · Reuse the section skeletons**: No extra scope · ≈6 files · easy to undo.
**1 · One new skeleton**: No extra scope · ≈2 files · easy to undo.
**2 · Inline**: No extra scope · 4 files · easy to undo.
**2 · Shared components**: Adds 4 components · ≈8 files · easy to undo.
**Source**: `app/dashboard/sections/*.tsx`, five exported section skeletons.
**For architect**: none.

</details>
````

Add a decision diagram only when a fact is easier to see as a branch. When `html_render` exists and a round changes what a user sees (a layout, a
state, or a flow between screens), through an option or an assumed default, its picture
is one mockup page: prototypes of the real screens, built as
[mockups](references/mockups.md) says. A round that changes no screen gets none. In the
fold, give each option:

- **Change**: what the option touches, named in its size, such as `1 file: export.ts`.
  Add a small `diff` of observable behavior only when names don't show it. Draw moves per [views](references/views.md). It shows scope, not design: code
  shape is `architect`'s call.
- **Cost line**: after the option's name, Scope · Size · Undo, such as
  `Adds a repository method · ≈3 files · hard to undo: migration`. Use the exact
  scope labels below for each option.
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
  choice is easy to undo. With one losing option, the question's other-option sentence can
  carry it.
- **Domain docs as you go**: use `domain-modeling` when an answer settles a domain term,
  the user's word is fuzzy or conflicts with the glossary, or a decision may need an ADR.
  Show a settled term in that question's fold and write it once the round is accepted;
  offer an ADR as an option in that turn.

## 4. Watch the whole plan

- **A wider answer** shows any new questions it creates in the next round.
- **A second PR**: when the plan's size passes ~20 files or one migration plus its
  callers, say so and propose a split into vertical slices, each shipping a working part of the outcome. A
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
  didn't pick, such as an assumption or a *My suggestion:* item, ends `[assumed]`.
- **Resulting shape**: one combined `diff` of the file tree the plan touches.
- **For architect**: the structure questions parked for `architect`, or none.
- **Scope and size**: the size trail and each widening with the answer that caused it.
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

Plan-ready uses the round's shape with one question, `❓ **1 · Approve this plan?**`, and every
addition the user didn't pick, including docs, tests and migrations, still a *My
suggestion:* bullet. The user's approval accepts
them, or they drop them.
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
```

To add it to a spec, ticket, or PR, show the exact section and its target, and on
approval replace or add only that artifact's Not in scope section, then link the result
once it shows.

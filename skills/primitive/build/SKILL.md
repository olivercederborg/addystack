---
name: build
description: "Implements an agreed plan in verified steps inside its scope. Use when asked to implement, build, or code up a plan, spec, or ticket, including \"build it\" after a plan was discussed or a pick that implements it."
compatibility: Requires git.
metadata:
  layer: primitive
---

# Build

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Card kinds here: **Decision** (a choice the plan didn't cover) and **Deviation** (the
build had to differ from the plan).

## 1. Load the plan

- **Plan**: the decisions, test seams, and **Not in scope** list from `scope-grill`,
  taken from this conversation or the ticket, plus the linked issue or spec, or the
  caller's brief.
- **Contract**: the interfaces approved with `architect`, when there are any. Build
  inside them; a change to one stops the build for the user, or, with autonomy, goes
  back through `architect`.
- **Domain terms**: read `CONTEXT.md` so names use the glossary's terms.
- **Standards**: the repo's guidance and conventions, and the **Lenses** skills from
  the chat format.
- **Branch**: confirm the current branch owns the change. In a stack, use the lowest
  branch that owns each change. A fix for something already broken on trunk or in
  production, found while building other work, belongs to no layer: start it on a new branch from trunk, or, as
  a writer child, return it as a Deviation card. Keep any
  uncommitted work out of the build.
- **Checks**: find the repo's focused typecheck, lint, and test commands.

When there is no agreed plan and the work isn't trivial, offer `scope-grill` first,
or, with autonomy, hand the request to the next step the router picks, which writes
the brief.

**As a writer child**, build the one layer in your task and commit each step.
When a step needs an interface change, a scope change, or a product call, stop and
return it as a Decision or Deviation card.

**Done when:** the decisions, the Not in scope list, the branch, and the check commands
are known.

## 2. Build in steps

Split the plan into small vertical slices, each a thin working path through the code,
and build one slice at a time:

1. **Ground** each non-trivial API call or pattern with
   [grounding](references/grounding.md) before writing it.
2. **Red.** Where behavior can regress, write the fewest tests that cover the step's
   distinct cases, at the plan's test seam, each asserting real behavior. Watch each
   fail for the right reason. Use `tdd` when it's installed, with the plan's test seams
   as the seams the user already confirmed.
3. **Green.** Write the smallest code that passes, using the glossary's names and the
   plan's decisions. Refactoring comes later, in `verify-work`.
4. **Check.** Run the focused checks for the touched files. A failing check stops the
   step until it's fixed.
5. **Run it.** Exercise the behavior itself: run the code, call the function, or use
   the UI. When the project has a verification skill (`verify-<app>`), drive a UI change
   through it and keep its evidence, and add a file to its feature map for a feature that
   has none, so the map grows with the work. When the plan is a design, such as a
   concept or mockup, measure the running screen against it at the same viewport. Each
   element it shows that today's code can build, and the plan's current scope covers,
   stays unfinished until it's built. Run
   each platform, OS, or flag branch the change reaches, forcing one locally when its
   runtime isn't installed.
6. **Commit** the step as its own atomic commit with the repo's tooling (for example
   `git commit` on a `gh stack` branch). Run the pre-commit checks in the repo's
   version-control guidance first, such as a comment-convention scan.

When a check fails and the cause isn't clear, use `diagnosing-bugs` when it's
installed: form a hypothesis you can disprove, then test it. Tag debug logs with a
unique prefix (`[DEBUG-a4f2]`), and remove them before the step's commit.

Run the full test suite once at the end. Then run `review-loop` once on the branch, unless
this build is a writer child's or `review-loop`'s, since the caller reviews.

## 3. Stay in scope

- **Needed but not planned**: show a **Decision** card in the
  [decision card](references/views.md#decision-card-example) shape, opening with **Proposed this round** · *my suggestion, not agreed*: a `diff`
  block of `+` additions and any Size change. Pick the option that best meets the
  plan's bar, and in the fold give each option its scope against the plan, as in
  `scope-grill`: `No extra scope`, `Drops …`, or `Adds …`. Build the addition only
  after the user's answer.
- **Listed as out**: items under **Not in scope** stay out, however cheap. If the build
  can't work without one, raise a Decision card.
- **Forced deviations**: when the code must differ from a decision (for example, an API
  doesn't support the planned shape), show a **Deviation** card with the reason and its
  sources.
- **Other decisions keep going.** A pending decision pauses only the steps that depend
  on it.

## 4. Report

````markdown
✅ **CSV exports now include each row's currency.**

```diff
  // src/export/export.ts: toRows owns the column order
  export const toRows = (txs: Transaction[]): Row[] =>
-   txs.map((t) => [t.date, t.description, t.amount]);
+   txs.map((t) => [t.date, t.description, t.amount, t.currency]);
```

- See it: `pnpm export --sample`, then open `out/transactions.csv`.

<details><summary>Checks: ⚠️ lint not run · ✅ 3 passed, and what each test covers</summary>

⚠️ lint not run (no config) · ✅ typecheck · ✅ tests 14/14 · ✅ ran it: export on sample data

- `export.test.ts`: from and to dates are included → rows kept ✅
- `export.test.ts`: currency column → `EUR` in every row ✅
- 3 steps, 3 commits · Deviations: none · Not in scope: untouched · review-loop: 1 blocker fixed

</details>
````

- **Headline**: what the build does now, in plain words. A failing check makes it 🔴,
  and a deviation 🟡.
- **Shape**: the smallest view of what the user hasn't seen, as [views](references/views.md) picks it:
  the changed interface with its call site, a call tree, the file tree, or none. Longer
  hunks stay in the PR.
- **Notes**: how to see it working, and each open Decision or Deviation card as a
  **Decide** item.
- **The fold**: the checks line, the step and commit counts, the tests added as one-line
  cases, any deviation, a confirmation that Not in scope was left alone, and
  review-loop's blockers, fixed or dropped.

Recommend verify-work, then a push and a draft PR. Push or submit per **Approval**: when
the user says so, or has granted autonomy.

**Done when:** every decision in the plan is implemented, all checks pass, the behavior
was run, review-loop is settled, nothing outside the plan was built, and
the user has seen the code.

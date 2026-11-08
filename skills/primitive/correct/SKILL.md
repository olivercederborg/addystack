---
name: correct
description: "Turns a mistake agents keep repeating in a repo into the strongest check that catches it. Use for /correct, when a correction lands twice (\"you did X again\", \"make this impossible\"), or when reflect hands one over."
metadata:
  layer: primitive
---

# Correct

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

The user keeps correcting agents in a repo for the same mistakes. Change the repo so the
next agent can't make them: each repeated correction becomes the strongest check that
works, proven failing on a real past mistake.

Assume every contributor is an agent that sees only the files it opened, copies the
nearest example, and takes the shortest path that compiles. Design the repo so a change
that looks right from one file is right for the whole repo.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Card kinds here: **Decision** (a class whose level is a product call, or an exception the
user must approve).

A **class** is one mistake shape with one fix, seen at least twice. A **ratchet** lets
existing hits stand and fails when a change adds more.

## 1. Find the classes

Read-only. First list what already enforces rules in the target repo (this checkout, or
the one reflect named): lint configs, the baseline or suppressions file and the guard
that reads it, typecheck strictness, CI's commands and what CI skips (drafts,
`paths-ignore`), and `AGENTS.md`'s rule table. Fetch the default branch when there's a
remote, and note its head as the base.

Then read every source in [mining.md](references/mining.md): review-fix commits and the
commits they fixed, reverts, PR review comments, CI failures, and the user's typed
corrections in T3 through `scripts/corrections.py`. When reflect hands a class over, its
citations are occurrences. Group by the shape of the fix. A class needs two cited
occurrences (a SHA, a PR comment or CI run URL, or a T3 thread and timestamp); list a
single one as skipped, with its citation.

## 2. Pick the level

Take the highest level that works for each class:

1. **Architecture**: one owner per piece of state, one supported way per task, internals
   hidden so the wrong import fails, and the old way deleted so nothing copies it.
2. **Types**, so the bad state can't be written.
3. **A lint or CI check** whose error names what to use instead. Ratchet it when the
   pattern is already common.
4. **A test** of the behavior.
5. **Docs or an agent rule**, only for a judgment call, since nothing fails when an
   agent skips them.

For each level above the pick, give the fact that rules it out: "one Result runner would
touch 122 call sites", "a type can't forbid try/catch".

## 3. Present

One row per class: its occurrences, level, enforcer, and why not higher; then the
skipped classes with reasons. Leave the repo untouched until the user picks, per
**Approval**. In a gated repo this list is scope-grill's input. In a repo whose findings
the user decides, such as a framework pilot, record each new rule there as a finding.

## 4. Build and prove

When the correction came from the current change ("you did X again"), build on its
branch and fix that occurrence there; otherwise branch from the base. One commit per
check. Baselines and exceptions follow [ratchet.md](references/ratchet.md):

- **Replay**: run the real lint, typecheck, or test command on the pre-fix file from
  `git show <fix>^:<path>`, in the tree or on stdin, and show it fail; then show the
  fixed file pass. Drop a sub-check with no past mistake, except the baseline guard.
- **Per occurrence**: under a per-file ratchet, report each call, not the import.
- **Baseline**: hits already on the base go in the repo's baseline, and only on the
  branch that turns the rule on. When the guard lets a baseline entry in for a rule
  already on at the merge base, closing that gap is its own check, proven by a repro.
- **Exceptions**: a new hit of a rule already on gets fixed, or an inline exception
  ending its disable comment, `-- <reason>, expires <YYYY-MM-DD>, approved by <user>`.
  Offer both as a Decision, and add the exception only once the user approves it.
- **CI**: run the same command locally and in CI, wiring a new check into CI's command,
  and say when CI skips it, such as on drafts or a `paths-ignore` match.

## 5. Place the rule

A check's error is the rule the next agent reads: it names the fix and the doc behind
it. Add a row to `AGENTS.md`'s rule table when the repo keeps one, and change nothing
else there. A judgment rule goes in the doc that owns its topic. Commit each doc change
on its own, then push or open a PR per **Approval**.

## 6. Report

````markdown
✅ **New Effect `.catch` calls and manual memos now fail `pnpm lint`.**

```text
$ pnpm lint
use-live-activity-actions.ts:73  no-promise-handling-of-effects
use-rest-alert-permission.ts:40  no-manual-memo
```

- Lint, not a type: one Result runner would touch 122 call sites.
- Skipped: a JSON cast seen once, and hand-rolled UI, which needs judgment.

<details><summary>Classes and replays: ✅ 2 fail before, pass after</summary>

| Class | Seen | Level | Enforcer | Why not higher |
|---|---|---|---|---|
| Effect failure handled on its promise | `87d02d3`, `0d12c66`, `2131f6f` | lint | `no-promise-handling-of-effects` | one Result runner touches 122 call sites; a type can't forbid `.catch` |
| Manual memo under the React Compiler | `fc63228`, `099b14e` | lint | `no-manual-memo` | the compiler can't reject a memo; types can't see it |

- `git show 87d02d3^:apps/mobile/src/features/session/live-activity/use-live-activity-actions.ts`
  into the tree, `pnpm lint` → `use-live-activity-actions.ts:73
  no-promise-handling-of-effects` (exit 1); fixed file → exit 0
- `git show fc63228^:apps/mobile/src/foundation/rest-alerts/use-rest-alert-permission.ts`
  into the tree, `pnpm lint` → `use-rest-alert-permission.ts:40 no-manual-memo` (exit 1);
  fixed file → exit 0
- Skipped: JSON cast (1 occurrence, `e880979`) · hand-rolled UI (judgment)

</details>
````

The enforcers' real output is the shape. The fold holds each class with its evidence,
level, and why not higher; each skipped class with its reason; and each check's replay
on its own line, as in the example: the command on the pre-fix file, its failing output
(file, line, and rule), and the fixed file's exit 0.

**Done when:** every class appears as built or skipped, and every built check shows its
replay, or the baseline guard its repro.

Adapted from Lauren Tan's `correct` in pstack (MIT); see [NOTICE](NOTICE).

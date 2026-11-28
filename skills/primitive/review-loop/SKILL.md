---
name: review-loop
description: "Runs Claude and Codex reviews of the user's own branch or diff, merges their findings, then fixes and re-reviews until clean. Use when asked for a second opinion, a Claude or Codex review, a cross-check, or another review pass."
compatibility: Requires git, plus T3 Code's `delegate_task` for the cross-provider reviewer.
metadata:
  layer: primitive
---

# Review loop

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

The main agent coordinates: it verifies, merges, reports, and fixes, and adds no
findings of its own.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

## Reviewers

Each reviewer runs on its provider's row of the **Reviewers** table in
[t3-delegation](references/t3-delegation.md), unless the user names other models for
this run.

**Fewer reviewers when one would repeat work:**

- **When verify-work reviews the same diff**, before, beside, or after the loop, round 1
  runs only the other provider's reviewer (Codex from Claude, Claude from Codex), since
  verify-work is this provider's review. When verify-work runs in the author's own
  context, as in Codex, run both.
- **Round 2 and later** run only the other provider's reviewer, on the fix commits and
  the code that calls them. Skip the round when every fix was a local Cleanup or
  Optional item and the focused checks pass.

The cross-provider reviewer is a T3 child task, run per
[t3-delegation](references/t3-delegation.md). The same-provider reviewer is a native
subagent when its model and effort, from the table or the user's override, match this
session's, and a T3 child task otherwise:

- `task`: `Act as the review sub-agent. Read <prompt path> in full and follow it.`, with
  step 2's prompt path.
- `target`: the reviewer's `driverKind` (`codex` or `claudeAgent`), model, and effort.
- `title` and `role` from t3-delegation's Reviewers, `interactionMode: "plan"`,
  `mode: "wait"`, and `timeoutMs: 1800000`.

If a reviewer fails (auth, budget, or timeout), continue with the other one, and label
the round **single reviewer** with the reason. Wait for every reviewer in the round
before reporting: reviewers are part of the round, not a background watch.

## 1. Pin the target

- **Explicit**: a PR, branch, commit range, or set of files the user names.
- **Plan**: a plan or design in this conversation, saved to a file for `packet.sh plan`,
  which asks for gaps, risks, and simpler options instead of code findings.
- **Branch**: diff against the stack parent, or against the merge-base with the default
  branch.
- **PR**: the live PR diff.
- **Working changes**: staged, unstaged, and untracked files that aren't gitignored or
  build output.

**Done when:** the target, base, and head are known.

## 2. Write the packet

Run `scripts/packet.sh <pr N | range PARENT..HEAD | working | plan FILE> --checks FILE`,
with each check already run as a `command → result` line in FILE. Add `--intent FILE`
for the user's plan or stated intent, `--only PATH` for each file the user names, and
`--keep PATH` for a lockfile, generated, vendored, or binary file the change's intent
names or edits by hand. It writes the packet and the one prompt every reviewer gets under
`.review-loop/` in the repo, and prints both paths and the loop's **baseline** size.
Every later round, and step 5's size check, reruns this command at the new head, with
`--base <round 1's Base>` for `working`. From round 2, add `--round N --previous FILE
--settled FILE`: the previous findings with their fixes, and every dropped, skipped, or
follow-up finding with why.

**Done when:** `packet.sh` printed the prompt path and the baseline.

## 3. Review, verify, merge

1. **Run both reviewers in parallel.**
2. **Verify each finding** by rerunning its command, running the one an unproven finding
   names, or reading the lines a doc or rule finding quotes at the head. Keep it when the
   output or the lines show what it claims, and drop the rest, including findings with
   neither, each with why in one line.
   Check each proposed fix against repo conventions and library patterns with
   [grounding](references/grounding.md). A convention finding whose only fix needs a cast
   or lint suppression is a follow-up; a cheaper fix is applied as usual.
3. **Merge.** Group findings by root cause, note who raised each (Claude, Codex, or
   both), and show severity disagreements as they are. The round's rating is the lowest
   a reviewer gave, re-banded when a finding it rests on was dropped.

**Done when:** every finding is verified or dropped, and merged by root cause.

## 4. Report

````markdown
🔴 **Round 1: a retry can charge a customer twice.**

```diff
  // src/retry.ts:40: a timed-out charge is retried with a new charge
- () => provider.charge(amount),
+ () => provider.charge(amount, { idempotencyKey: attempt.id }),
```

- **1** · Blocker · a timed-out charge charges again · `retry.ts:40` · both → fix, above
- **2** · Cleanup · backoff never caps · `retry.ts:12` · Codex → fix
- **3** · Cleanup · no timeout-path test · `retry.test.ts` · Claude → fix

<details><summary>Checks: ✅ 3 passed · Claude 2, Codex 2, 1 shared, 1 dropped</summary>

✅ typecheck · ✅ tests 22/22 · ✅ idioms (the repo's lenses, grounding, taste) · rated 5/10: a retry double-charges

- **1** · `src/retry.ts:40` · verified by rerunning `bun test retry.timeout.test.ts`: 2 charges, intent 1 · source: provider idempotency docs
- Dropped: Codex's "unhandled rejection" at `queue.ts:8` · doesn't hold: caught at line 12

</details>
````

- **Headline first**, with the round number: 🔴 with what breaks in plain words when
  there's a Blocker, 🟡 with only Cleanups, and ✅ **Clean** when nothing needs fixing,
  including a round with no findings.
  A round with findings to fix recommends fixing them, one commit each, and
  re-reviewing until Clean.
  A clean round ends by recommending verify-work, then open-pr, leaving out a step
  that already ran on the current head.
- **Shape**: the worst finding's fix as a `diff` of the enclosing code.
- **Findings** each name who raised it.
- **The fold**: the reviewer counts, the checks line, one evidence line per finding, and
  each dropped finding with why it doesn't hold.

## 5. Fix and re-review

One approval runs the loop, as does autonomy under **Approval**: apply the approved
fixes, then keep going round by round, fixing each new finding whose call is **fix**,
without asking between rounds. Stop and report when a round is **Clean**, at the round
cap, or when a round brings a Decision card, a blocker whose fix changes the design, or a
repeated class of finding. With autonomy, take a Decision card's recommendation, send a
design change back through `architect`, log both, and keep going.

1. Apply each fix, at every place its class names, on the branch that owns it, run the
   focused checks, and commit it as its own atomic commit. When a caller that builds
   in layers runs this loop, make each fix with `build`.
2. **Cut first.** Rerun step 2's command. When its baseline grew, read the growth, and
   cut or narrow any added code no fixed finding needs, such as a new helper, option,
   guard, or test for a case the intent doesn't reach. Make each cut as item 1 makes a
   fix, then measure again. Growth a fixed finding needs stays.
3. Run the next round as **Fewer reviewers** says, counting cuts as fixes.
4. Report only what is new or still open, with the size in the fold's checks line, as
   `diff +120 −30 → +150 −30`. New findings continue the numbering.

After three rounds without **Clean**, start no fourth: fix the third round's findings whose
call is **fix**, then list what's still open and let the user decide.
With autonomy, put the open findings at the top of the PR description instead and go
on; a later fix still gets verify-work's re-check.
Every round counts toward the three, including a "confirmation" round. When a round's
findings repeat a class an earlier round fixed (new edge cases of the same guess), run
grounding first: how the library's own tooling solves it, and whether the real input can
reach the cases. Then recommend that pattern, or list the cases as known limits, before
offering another round. When the loop stops, push the fixes if the branch is the user's
own and already pushed; otherwise push per **Approval**.

**Done when:** every line of growth past the baseline belongs to a fixed finding or was
cut, and the loop has ended: a round is **Clean**, the user has fixed, deferred, or
dropped every remaining finding, or, with autonomy, the round cap was reached and the
open findings lead the PR description.

## 6. Record

When the loop ends, run `packet.sh clean`. On a PR, branch, or range, first record its
result for the branch's current head, against the packet's Base:

`python3 scripts/verdicts.py review <Base> <head> --rounds <N> --rating <R> --reason '<why>'`,
with the last round's rating, re-banded when a later fix closed the finding it rests on.

The ready gate (`hooks/ready-gate.py`) marks a PR ready only with a result for its
current diff. Record `--skip '<reason>'` instead when the user skips the loop, or for a
fix after the round cap, and name the skip in the PR's checks line.

**Done when:** `verdicts.py review` printed the result for the PR's current head.

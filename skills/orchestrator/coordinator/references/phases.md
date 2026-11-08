# Phases

Read at coordinator step 7, once the phase's proof holds. A project runs in phases: each
has its own goal and proof, and ends here. The project closes only on the user's word.

1. **Integrated check**: run [close](close.md)'s integrated check on every unmerged
   project PR, and record its result, the heads, and the trunk SHA it ran at under
   Decisions. With no unmerged PRs, skip it.
2. **Promote**: copy each decision and learning that binds the next phase into
   `standing-rules.md`. Write into Goal's Follow-ups each follow-up whose detail lives in
   Decisions or Learnings, and each later phase Goal names, with its proof. Set each
   worker whose PR is still open to `waiting`, with Waits on `#N open`, so its row and
   thread stay for the PR's watch. `phase` empties Decisions and Learnings into the
   archive, which a wake doesn't read; only close reads it.
3. **One card**: bring the user one decision card, as in step 5, with three options:
   start the next phase, park, or close. Make the next phase option `a` when
   `project.md` or the user already named it, with its goal and proof.

Then follow the pick:

- **Next phase**: run `scripts/project.py <folder> phase <slug> --result <one line>
  --goal G --proof P`, then return to SKILL.md step 2 with the new goal.
- **Park**: run `project.py <folder> phase <slug> --result <one line> --park <reason>`.
  Once no worker is `running`, `waiting`, `overdue`, or `unknown`, delete the heartbeat
  and startup timer and set their Listening lines to none. Unwatch each merged PR. Keep
  the thread pinned, and reply with step 5's one-line status.
- **Close**: follow [close](close.md).

`phase` saves `project.md` to `phases/`, adds the Phases line, and resets the phase's
sections ([project](project.md#phase-end)). A user message on a parked project that
names new work starts the next phase: run `project.py <folder> start --goal G --proof
P`, then return to SKILL.md step 2.

**Done when:** the integrated check passed or had no unmerged PRs, every binding decision
and learning is in `standing-rules.md`, every follow-up and named later phase is in
Goal's Follow-ups, every open PR's owner is `waiting`, and the project is in step 2 of
its next phase, parked (its heartbeat deleted once no worker runs), or in close.

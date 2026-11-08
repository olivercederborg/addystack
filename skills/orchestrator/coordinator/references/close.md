# Close

Read at coordinator step 7, once the goal's proof holds.

Run the **integrated check**, which proves the PRs work together, not only one by one.
Start a fresh `delegate_task` verifier on this machine, with `isolation: "worktree"`, a new `clientRequestId` for each run, and the goal and its
proof, every PR's head SHA and base, Decisions, and each worker's verdict. It takes a
slot, since it builds. In its own worktree it merges every unmerged project PR branch
onto the current trunk they target, merging nothing on GitHub, runs the repo's checks
there, and reports missing outcomes and anything that breaks across PRs. Send each
finding to the worker that owns that code as a fix, and rerun the check after any fix
that touches what it covered. Record its result under `## Result` in `project.md`.

Then account for every worker as done, replaced, or absorbed. Delete the heartbeat
and any startup timer, remove every watch, and write the final summary under
`## Result`. Then unpin this thread with `t3_thread_organize`.

**Done when:** the integrated check passes at the PRs' current heads, or the user
accepted a stated limitation through a decision card, recorded under Decisions;
Listening is empty, every worker row has a final state, and the thread is unpinned.

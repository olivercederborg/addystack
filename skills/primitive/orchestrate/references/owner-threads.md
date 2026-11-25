# Owner threads

Read before launching an owner thread: a top-level thread that owns one PR and watches
it. Owners share two slots, so at most two build or run heavy checks at once. An owner
holds its slot until its PR reaches maintenance done, not just until its draft opens.
Queue the owners past two. Every launch, a queued owner's and a relaunch included,
passes the PR owner row of [t3-delegation's Roles table](t3-delegation.md#roles) as
`modelSelection`, since a launch without one takes the launching thread's model.

Every message to an owner carries the standing rules file in full, and each new line
goes to every open owner at once.

A launched thread doesn't wake the thread that launched it. So while any owner is open
or queued, run an hourly check: `schedule_task` with
`{type: "interval", everyMs: 3600000}`, posting into this thread, with a prompt that
names the standing rules file's path and this file's path to read first. Each run, and any other wake of
this thread:

- **Checks each owner by what it produced**: new commits on its branch, its PR's state,
  its thread's status from a status read with `t3_thread_read`, and its watch from the
  `watching` field of `list_thread_pull_requests` with the owner's `threadId`.
- **Posts only changes** since the last run, and stays quiet when nothing changed.
- **Replaces an owner** only when its thread's status in `t3_thread_read` is `failed`.
  Relaunch it with `t3_thread_launch` and
  `workspaceStrategy: {type: "existing_worktree", worktreePath, branch}`, on its
  existing worktree and branch, in the failed owner's slot, before any queued owner
  launches, so no third owner builds. An owner the user stopped (`interrupted` or
  `cancelled`) stays as it is.
- **Reports a stuck owner** that hasn't failed: one running with no new commits, idle
  at a stop (an approval, a credential), or idle without a watch. Name what it waits
  for. It keeps its PR and its slot.
- **Launches queued owners** into the slots that freed, oldest first.
- **Reports a probe it can't read**, such as a failed `t3_thread_read`. It's neither a
  pass nor a reason to replace.
- **Deletes the schedule** with `delete_scheduled_task` when the last owner finishes
  and the queue is empty.

An owner merges by the repo's trust value. A go that names merging
counts only as the user's own words, typed in the owner's thread or quoted by the parent.

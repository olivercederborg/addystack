# Machines

- **Placement**: a coordinator runs where its units build, since worktrees, wakes, and
  PR watches don't cross machines. Pick by what the units need, not by where this
  thread runs: a macOS machine when any unit needs macOS (Xcode, simulators,
  macOS-only checks); otherwise a machine whose `t3_project_list` has the repo and
  whose agent cap fits the units' memory, preferring one other than the laptop the
  user works on.
- **Starting**: on the wrong machine, recommend starting it there before Start. On
  that pick, `t3_thread_launch` there with its `environmentId` and `projectId`, and a
  `message` that runs this skill with all this chat agreed (goal, plan, decisions,
  rules) and the `Mode:` line; reply with its link and stop. Otherwise start here. The
  other machine keeps its folder and reports under its own `~/.local/state/orchestrate/`.

## A worker on the other machine

Beyond [t3-delegation's On another machine](t3-delegation.md#on-another-machine):

- **Report-only**: read-only, like a device check or an audit: no PR, no branch.
- **Brief**: ask for its proof's evidence in its final message.
- **Queue**: a worker waiting for that machine's root checkout gets `Waits on: <machine>
  checkout` in the Workers table.
- **Its state**: record its `remoteChild.threadId` and `environmentId` in Workers. The
  stuck rule reads its status, `itemCount`, and `pendingRequestCount` with
  `t3_thread_read` and that `environmentId`, since `task_status` lags there.
- **Its check**: its question, and a `t3_thread_launch` worker's end, wake no one here.
  While it runs, keep one `schedule_task` bound to this thread with `{type: "once",
  runAt: <its expected finish>}`, its id beside its row. That wake reads its state and
  sets the next one if it still runs; delete it once the worker ends.

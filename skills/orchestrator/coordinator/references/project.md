# project.md

The coordinator's memory for one project, at
`~/.local/state/orchestrate/<project>/project.md`. The coordinator is its only writer.
Start it with `scripts/project.py <folder> init`, and write decisions, learnings,
Workers rows, and Listening lines with `project.py` (`decide`, `learn`, `worker`,
`listen`; `--help` shows each). Its sections:

- **Goal**: one sentence a stranger could act on, its `Proof:`, and `Follow-ups:`,
  scope drift a worker found, kept out of the goal.
- **Decisions**: `<worker> asked <question> → <answer> · <source>`, the source being
  "the user: '<their words>'", the plan, standing rule <n>, or what the probe showed.
- **Learnings**: `<worker>: <lesson a sibling worker should know>`.
- **Listening**: the `Heartbeat` and `Startup` scheduled task ids, or none, and
  `Watches`: each watched PR with its owner.

## Workers

- **Thread**: the worker thread's `link`, verbatim, as T3 returns it
  (`<t3-thread://…>`), the link every card for that worker carries. Add the `taskId`
  beside it for `task_status` and `task_cancel`.
- **State**: `queued`, `overdue` (launched, not started by the startup deadline),
  `unknown` (its status read failed), `running`, `waiting` (on a call), `stuck`, `done`,
  `replaced by <worker>`, `absorbed into <worker>`, or `dropped` (after two retries,
  with the replan in Decisions). Add `retry <n>` while a unit is on a retry.
- **Waits on**: the call, credential, slot, shared resource, or worker it waits for,
  with the time it started waiting. The queue of cards reads this column.
- **Last side effect**: the newest commit, push, or PR event seen, with its time, or for
  a report-only worker its thread's `itemCount`. The heartbeat compares against it to
  find a stuck worker.

## Close

At the close, add `## Result` under Goal: the integrated check's result (the head SHAs
it merged, the checks it ran, and a pass, or the limitation the user accepted), what
shipped, with each PR and its merge state, each worker's final state, and the follow-ups
left open.

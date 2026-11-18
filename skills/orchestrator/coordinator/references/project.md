# project.md

The coordinator's memory for one project, at
`~/.local/state/orchestrate/<project>/project.md`. The coordinator is its only writer.
Start it with `scripts/project.py <folder> init`, and write decisions, learnings,
Workers rows, Queue items, and Listening lines with `project.py` (`decide`, `learn`,
`worker`, `queue`, `listen`; `--help` shows each). End a phase with `phase`, and start
the next on a parked project with `start` ([phases](phases.md) says when). Its sections:

- **Goal**: the current phase's goal, one sentence a stranger could act on, its
  `Proof:`, and `Follow-ups:`, scope drift a worker found, kept out of the goal. A
  parked project's Goal is `Parked <date>: <reason>` and its Follow-ups, with no
  `Proof:`.
- **Phases**: one line per finished phase, `- <date> · <NN-slug>: <result> · <archive>`,
  added by `phase`.
- **Queue**: what waits on the user, as step 5 orders it: a row per real call, stuck
  run, or Do, with the id its turn-block need carries, never reused, and `Next id:` above
  the table. `queue add` and `queue done` are its only writers, and `done` adds the item,
  who asked it, and the answer under Decisions. A phase end carries it over. A project
  from before the queue starts it with `queue import`, given a turn block naming every
  item still open, with `--from <id>=<worker>` and `--stuck <id>` for what a block can't
  say, and `queue add` refuses it until then.
- **Decisions**: `<worker> asked <question> → <answer> · <source>`, the source being
  "the user: '<their words>'", the plan, standing rule <n>, or what the probe showed.
- **Learnings**: `<worker>: <lesson a sibling worker should know>`.
- **Listening**: `Heartbeat`, `tick` while the [tick](tick.md) checks the project, or
  none; `Startup`, its scheduled task id or none; and
  `Watches`: each watched PR with its owner. Each recurring check is a `Duty <name>`
  line, `<task id> · <cadence> · <source> · until <end> · last <ISO time>, <n> new`, or
  `none (ended <date>: <reason>)` once it ends. Its findings so far are in
  `duties/<name>.md` beside `project.md` ([duties](duties.md)).

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
  a report-only worker its thread's `itemCount`.

The tick keeps what it last saw in `tick.json` beside `project.md`, and is its only writer.

## Phase end

`phase` saves `project.md` byte for byte to `phases/<NN>-<slug>.md` in the project
folder, so a wake reads only the current phase and the archive holds the rest. It then
empties Decisions and Learnings, removes each Result section, drops Workers rows in a
final state (`done`, `dropped`, `replaced by`, `absorbed into`), and writes the new Goal
or the parked one, keeping Follow-ups. Every other section and line carries over.

## Close

At the close, add `## Result` under Goal: the integrated check's result (the head SHAs
it merged, the checks it ran, and a pass, or the limitation the user accepted), what
shipped, with each PR and its merge state, each worker's final state, and the follow-ups
left open.

<!-- Copy of shared/t3-delegation.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Delegating in T3 Code

T3 Code's `t3-code` MCP server runs a task on any provider as a child thread of this
one.

## Once per session

- Load `orchestrator_capabilities`, `delegate_task`, and `task_status` together. In
  Claude Code that is one `ToolSearch` with `select:`. Call `orchestrator_capabilities`
  once per thread, before the first `delegate_task`.
- Take each `target` from the Roles or Reviewers table, the calling skill, or, for
  Codex's model, `~/.codex/config.toml`. The effort option is `effort` on
  `claudeAgent` and `reasoningEffort` on `codex`, with values `low`, `medium`, `high`,
  `xhigh`, and `max`. A wrong model or option value fails before the child starts, and
  a wrong option's error lists the valid values.
- After `delegate_task` returns a failure for an optional review, say so and continue
  without the second model, as the skill says, for the rest of the session.

## Roles

| Role | `target` | Effort |
|---|---|---|
| Writer: a stack's layers | `claudeAgent`, `claude-opus-5-5` | `medium`, or `high` for a layer marked hard |
| Third sketcher: architect | `claudeAgent`, `claude-opus-5-5` | `high` |

Run these roles through `delegate_task`, even when the model matches yours, so the
effort is set. They're required: when the child fails, report its layer or sketch as not
done, and leave it undone rather than doing it yourself. Verifiers keep the models their
own skills name.

## Reviewers

A child on the other provider that reviews work, such as a PR, a plan, a transcript, or
another child's diff, runs on that provider's row, unless its skill names another
model:

| Reviewer | `target` | Effort |
|---|---|---|
| Codex | `codex`, `gpt-6.1-terra` | `max` |
| Claude | `claudeAgent`, `claude-opus-5-5` | `high` |

Give a reviewer `role: "review"`, the title `◎ <PR #N or unit> r<round> · <reviewer
model>`, such as `◎ #312 r1 · gpt-6.1-terra`, and `timeoutMs: 1800000`, since `max`
effort can run long. A child that reviews nothing, such as a grader or a sketcher, takes
another role.

## The call

- **`task`** carries everything the child needs. The child sees only this text, never
  this conversation, so pass files by absolute path. When the user's instructions give
  the target repo a mode, start `task` with its `Mode:` line. End it with the report
  block below.
- **`target`** names `driverKind` (`codex`, `claudeAgent`) and `model`. Always name the
  model: switching provider without one takes that provider's first listed model. Set
  `options`, such as effort, from the values in Once per session.
- **`clientRequestId`** is a stable key per task, so a retry returns the same task.
- **`mode: "wait"`** blocks until the child finishes or `timeoutMs` passes. On
  `waitTimedOut: true` the child keeps running: read `task_status` once, and if it is
  still working, end the turn.
- **`mode: "async"`** returns at once, so end the turn.

## On another machine

`t3_environment_links` lists the user's other machines, such as `buildbox`, and whether
each answers now. Send a child there when it would load the laptop for long, as a Codex
review, verify-work, or a browser run does, and everything it reads is pushed. When the
machine isn't `reachable`, run the child here and say so in your report.

- **Target**: add `environmentId` to `target`, and take `projectId` from
  `t3_project_list` with that `environmentId`, since this machine's project ids don't
  exist there.
- **Checkout**: the child runs in that project's root checkout, on whatever branch it
  holds, and has none of this machine's commits until it fetches them, pushed ones
  included. `isolation: "worktree"` is rejected there. So a `delegate_task` child there
  reads a branch without checking it out: `git fetch origin <base> <branch>`, then
  `git diff origin/<base>...origin/<branch>`. A child that checks out, builds, tests, or
  writes is a `t3_thread_launch` with `environmentId` and a `worktree`
  `workspaceStrategy` on the pushed branch.
- **One at a time**: every `delegate_task` child there shares that project's root
  checkout, so run one per project at a time and queue the rest. A `t3_thread_launch`
  worktree child has its own checkout and doesn't wait its turn.
- **Waiting**: start it with `mode: "async"`. `mode: "wait"` never sees the child end:
  it blocks for its whole `timeoutMs`, then returns `waitTimedOut: true`. `task_status`
  keeps saying `working` after the child ends, and the completion wake can come half an
  hour late. Call `t3_thread_wait` on the returned `remoteChild.threadId`, with its
  `environmentId`, then read the child's last message with `t3_thread_read`.
- **Report**: write the report path with that machine's home, such as `/home/<user>` on
  Linux, and open it with `ssh <machine> cat <path>`.
- **Settle**: the child is a top-level thread on that machine, so it shows in its
  sidebar. Once you've read its result, settle it with `t3_thread_organize`, passing its
  `environmentId`.

## The report

The child's last message is its result. Every `delegate_task` and `task_status` call
returns it twice, as `summary` and `latestTerminalSummary`, and it stays in this
thread's context. So the child writes its evidence to a file and returns a short
report. End `task` with this block, filling in the path:

```text
Report. Write your full report to <path>: every check with its output, the tests you
added, grounding, evidence, and anything else worth keeping. Then end with a message to
the parent agent holding only these, one line per entry, and leaving out an empty item:
1. Status: done, partial, blocked, or failed, the verdict, and what works now.
2. Branch and head SHA, then each commit as `<sha> <subject>`.
3. Each new or changed interface a later step builds on, such as a type, route, file,
   or prompt, as its signature.
4. Each finding the task asked for, with its `file:line`.
5. Each check you ran, with its result.
6. The calls you made that a reviewer would ask about, as show-me-your-work's
   `scripts/decisions-table.sh --calls <log>` prints them from the log your task names,
   then each deviation and what you didn't verify.
7. Any Decision or Deviation card, in full.
8. Full report: <path>.
9. With a `Project:` line in this brief, a turn block whose `project` is that name
   (the Turn block section of the user's reply rules: the `replies.rules` file
   `<kit>/bin/addystack print-config` names, or their instructions when it's null, or
   `<kit>/references/turn-block.md` when neither has one).
```

- **`<path>`** is `<home>/.local/state/orchestrate/reports/<clientRequestId>-<six random
  hex characters>.md`, with the home directory spelled out. The suffix keeps tasks that
  reuse a `clientRequestId` apart.
- **A read-only child**, such as a reviewer or a sketcher in `interactionMode: "plan"`,
  gets no block: it can't write the file, and its findings or sketch are the result
  itself.
- **An eval player** keeps the brief `evals.py` writes, since its reply is under test.
- **Open the file** when a step needs the detail: a PR's checks and evidence, a
  verify-work packet, a decision log's evidence, or a claim to check.

## Reading a child or thread

A child's completion wakes this thread with a notification that names the task, not its
result: read `task_status` once for the summary. Read a child's thread only for what the
summary lacks, such as its commands (`view: "activity"`).

`t3_thread_read` starts at the oldest item unless `afterPosition` is set. Positions count
every item, activity included, and `afterPosition` is exclusive:

- **Status**: `limit: 1` and `maxCharsPerItem: 200`. The `thread` field holds the
  status, branch, pull requests, and `itemCount`.
- **New messages**: `afterPosition` from the last read's `nextPosition`. On a first
  read, use `afterPosition: itemCount - 20` from the status read, or leave it out when
  `itemCount` is 20 or less. Then page on `nextPosition` while `hasMore` is true.
- **A long item**: when one you need has `textTruncated: true`, read the rest with its
  `itemId` and `textOffset: nextTextOffset` until `nextTextOffset` is null.

Check a child read-only with these, because `t3_thread_send` to an idle thread starts a
new run.

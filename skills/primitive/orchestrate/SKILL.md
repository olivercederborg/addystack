---
name: orchestrate
description: Coordinate subagents when a task has at least two independent workstreams, or when exploration, tests, logs, or research would add substantial noise to the main context. Do not use for small, sequential, or tightly coupled work.
metadata:
  layer: primitive
---

# Orchestrate

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Spawn at most one subagent per independent workstream, plus one per lookup whose raw output (logs, test runs, search dumps) you won't reread. Do everything else yourself.

Use read-only explorer agents (Codex `explorer`, Claude Code `Explore`) for independent discovery.

Use writer agents (Codex `worker`, Claude Code `general-purpose`) only when implementation ownership can be divided by file or module without overlap. Tell writers that they share the worktree, must preserve other changes, and must not revert another agent's work.

**Effort.** In Codex, give narrow lookups low reasoning effort, broader investigations and writers medium, and only difficult or ambiguous work high, with `fork_turns: "none"` whenever you override it. In Claude Code, keep each agent type's default model and effort, unless the calling skill or the user assigns one.

Give each fresh-context agent a brief, per **The brief** below. Tell leaf agents to complete their assignment directly and not delegate.

Before delegating, check that no agent already owns the work. Keep assignments distinct, and keep the models and roles a skill or the user assigned. Do not let agents edit the same files concurrently. Use one writer when work is sequential, tightly coupled, or touches shared mutable state. Let agents message each other directly when one result unblocks another assigned task.

Keep user communication, approvals, integration, final verification, and the final answer with the parent agent. An owner thread is a parent for its own PR. Continue useful parent work while subagents run, then synthesize their results without duplicating completed investigation.

When more work follows a finished child, start a fresh child with the consolidated
scope. A project worker, whose brief has a `Worker of:` line, is the exception to this
and to In T3 Code's `t3_thread_launch` for PR work: the project's thread starts it with
`delegate_task` in its own worktree, where its stack lives, and reuses it, or a
subthread. A child that returns no result leaves a gap: report its work as not done, never as a pass.

## The brief

A fresh-context agent has nobody to ask, so the brief is the product. Every brief names goal, scope, verify, and report. Add the other fields when the task is bigger than one command:

- **Mode**: the brief's first line, when the user's instructions give the target repo a
  mode, as in `Mode: planning autonomous, trust merge-on-go`.
- **Goal**: one sentence a stranger could act on.
- **Standing rules**: the user's rules from this chat, quoted verbatim, since a fresh
  agent sees none of the chat. For a program (owner threads, or more than one brief),
  write them first to `~/.local/state/orchestrate/<program>/standing-rules.md`, one
  numbered line each, with a short slug for `<program>`, and paste that file in full,
  as it stands. A new orchestrator session lists `~/.local/state/orchestrate/` to find
  it, past the `reports/` folder that child reports go to. When you catch yourself
  restating a rule, or one owner's lesson fits every owner, append it before you act,
  marking a lesson as yours.
- **Scope**: the paths it may write and its worktree or branch.
- **Context**: file and PR pointers, the relevant repository rules, and upstream reports pasted in full.
- **Acceptance**: checkable criteria, one per line.
- **Verify**: the exact commands to run.
- **Timebox**: when to stop and return partial findings.
- **Forbidden**: the repo's stacking tool (such as `gh stack`), rebase, and force-push stay with the parent, except
  in an owner thread's or a project worker's brief, since each pushes and restacks its own PR.
- **Report**: status, branch, head SHA, what it ran, and deviations. A `delegate_task`
  child gets the block in [t3-delegation's The report](references/t3-delegation.md#the-report)
  instead.

## In T3 Code

When the `t3-code` MCP server offers `delegate_task`, follow [t3-delegation](references/t3-delegation.md) and pick the tool by where the work runs:

- Same provider and model: a native subagent, unless the Roles table in
  [t3-delegation](references/t3-delegation.md) names the role. Those run through
  `delegate_task`.
- Another provider or model: `delegate_task`.
- Separate PR work: `t3_thread_launch` with `workspaceStrategy: "worktree"` and the PR owner row of the Roles table as `modelSelection`. For a stacked PR, set `baseRef` to the parent branch and `startFromOrigin: false`.
- Long or heavy work on pushed code, such as a review, verify-work, or a browser run: another machine, per
  [t3-delegation's On another machine](references/t3-delegation.md#on-another-machine).

Run long children with `mode: "async"`. Send the review of a child's work to a fresh child on a different provider from the one that wrote it, on the **Reviewers** target in [t3-delegation](references/t3-delegation.md), so the parent's turn stays on coordination. After a failed or lost launch, check `t3_thread_list` before launching again, with `includeSubagents: true` for a `delegate_task` child, since a `task_not_found` on a rebuilt task id doesn't mean it never started. Retry `delegate_task` with the same `clientRequestId`; `t3_thread_launch` has no retry key.

## Owner threads

A project the user runs from one thread takes the router's Project route instead. An owner thread is
a top-level thread that owns one PR and watches it. Before launching one, and on every
wake while owners are open, read [owner threads](references/owner-threads.md): its two
slots, the hourly check, and replacing a failed owner.

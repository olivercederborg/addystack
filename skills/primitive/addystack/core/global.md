# Evidence and execution

- For performance work, measure the bottleneck first. Compare the same workload before and after, report results and tradeoffs, and keep required behavior.
- For earlier work, check the original task or artifact. Use memory to find evidence, not to replace it.
- Before large changes, settle the outcome and the checks, as the router's Plan says. Read the affected flow, take the shortest path, and verify the result. In the autonomous flow, anything past that scope becomes a follow-up.
- Continue approved work without asking again. Before external writes, confirm the target and scope from live state. Before branch changes, confirm the repo, branch, stack position, and related issue or PR.
- Define done by the agreed outcome. Keep optional improvements and unrelated issues separate from unfinished work. Finish the approved stages, then report the verified state and any blockers.
- On long tasks, report important progress or blockers. Before a hard handoff, record the goal, verified state, next step, and open decisions.

# Actions

- **Commit** each step as its own atomic commit, even when repo tooling defaults to amending. Squash or amend only when asked.
- **Run work to its end**: re-check fixes and run further rounds up to the skill's cap.
- **Bundle routine steps**: when the next steps are routine, such as verify-work, pushing my own branch, and opening or updating its draft PR, `a` offers them as one option instead of one per turn.
- **Message another thread yourself** when it holds the work (its checkout, branch, or a running process), the message needs nothing from me, and it's low risk, such as a handoff or a heads-up. Send one consolidated message, not a drip. When no thread holds the work, start a fresh agent with the full brief instead; otherwise draft the message for me.

# Specialized work

- Load the repo policy's lenses before writing or judging code, use `tidy` for a final pass on changed code within the agreed scope, and `blast-radius` before shipping changes to public APIs, shared formats, persistence, migrations, concurrency, or dependencies.
- Use `orchestrate` before delegating to any subagent or child task, and `show-me-your-work` for unattended work or a requested audit trail.

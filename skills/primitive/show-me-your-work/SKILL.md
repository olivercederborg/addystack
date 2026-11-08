---
name: show-me-your-work
description: "Keeps a reviewable decision trail for long-running or unattended work: a TSV log, one row per decision (what, why, evidence, result). Use for /show-me-your-work, autonomous or multi-phase runs, or work a human reviews after stepping away."
metadata:
  layer: primitive
---

# Show me your work

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

A decision trail lets a reviewer reconstruct what was decided, why, and on what evidence, without rerunning the work or reading the whole transcript. Keep one canonical log so the trail is consistent and a future agent can find it.

## The format

A single TSV file, one row per decision. Cells stay single-line.

`scripts/log.sh` writes the header (`references/decision-log-template.tsv`) on a new log; a run that already has a log, such as one architect started, keeps appending to it. Columns:

- **ts.** ISO8601 timestamp.
- **phase.** The phase or workstream.
- **decision.** What was chosen or done, one line.
- **why.** The reason in plain words, even when a principle drove it (`explored options first, this was a one-way door`), not a jargon tag.
- **evidence.** A link or path that proves it: commit SHA, PR number, `file:line`, or an artifact, trace, or screenshot path. Never a paragraph. A major decision also cites its GitHub issue, or says `no issue`. Prefer evidence produced by committed scripts over hand-made one-offs, so a reviewer can re-run it (the **encode-lessons-in-structure** principle).
- **result.** The outcome or predicate state: `tests green`, `reverted`, `pixel-diff 0`, `INCONCLUSIVE`, `open`.
- **pr.** `you` or `agent` on a call a PR reviewer would ask about: hard to undo, surprising without context, or a real trade-off. Write its why as `instead of <option>; assumes <condition>`. Leave it empty on every other row. A call that should outlive the PR also gets an ADR.

An example, for illustration only; don't copy these rows into a real log.

```
ts	phase	decision	why	evidence	result
2026-05-24T09:02:00Z	frame	counted the work first, about 100 components and roughly 75 hours	wanted to know the size before starting a long run	commit 3a9f1c2	found 5 things to sort out before starting
2026-05-24T09:40:00Z	harness	took screenshots of the old version before changing anything	so we can compare old against new and catch any visual change	scripts/snapshot.sh, baseline/	saved 120 reference screenshots
2026-05-24T11:15:00Z	widget	moved the widget styles over without changing how it looks	keep the change small and the result identical	commit 7c21e0a, pixel-diff 0	looks identical, tests pass
2026-05-24T12:30:00Z	widget	threw out a helper's work because its screenshots were blank	checked the real files instead of trusting its summary	worktree reset	reverted, tightened the instructions for next time
```

## Logging a row

Write each entry the way you'd tell a teammate what you did: plain words and concrete actions, no AI speak or abstract jargon, so a reviewer understands each row without decoding it. The **unslop** skill, when it's installed, applies to log text too.

Append each row with `scripts/log.sh [--pr you|agent] <logfile> <phase> <decision> <why> <evidence> <result>`, which stamps `ts`, writes the header on first use, keeps every row well-formed, and refuses a `--pr` row whose evidence has no `path:line` or commit SHA. `scripts/log.sh import <logfile> <plan>` logs each `D<n>.` decision of a saved plan or brief, as `agent` when it ends `[assumed]`. A plan's `D<n>.` is its number in the PR table too, and a later `--pr` row with the same `D<n>.` or text replaces that decision, so log a built decision again with its code.

Log decision points and checkpoints, not every action: a fork chosen, a unit completed with its verification result, a pivot or revert with its trigger, a blocker surfaced, a gate fixed. For loop runs, one row per iteration. One row is one decision or checkpoint; if it doesn't fit on one line, the decision isn't crisp yet. The log is append-only: a wrong call gets a new row that supersedes it, and history is never edited or deleted.

## Where it lives

Keep the log at `decisions.tsv` in the work dir, or `.audit/<task-slug>.tsv` when several efforts run at once, and leave it out of git. The local log still keeps the run honest and can be discarded after.

Commit it only when the work is ambitious enough that a reviewer needs the trail to trust the result: a large cross-language port, a multi-week migration, anything where confidence has to be shown rather than assumed.

## Audit the log against the transcript

At the end of the run, before handing back, check the log told the truth. Read only this run's own transcript, since globbing across sessions reads unrelated private chats: in Claude Code, `~/.claude/projects/<project>/$CLAUDE_CODE_SESSION_ID.jsonl`; in Codex, the newest rollout file under `~/.codex/sessions/` for this thread. When the transcript path isn't available, audit against the tool outputs, files, git history, and other artifacts that are. Walk the log against what actually happened:

- Every row maps to a real action. Cut invented or aspirational entries.
- Each row's evidence resolves and shows what the row claims.
- A fork, pivot, or abandoned approach that shaped the work but isn't logged is a gap. Add it.
- Drop padding: a row nobody would audit doesn't earn its place.

Fix the log, not the story: if the work diverged from what a row claims, the row is wrong.

## Cross-model review of the trail

Before handing back, you must spawn a subagent on a different model family from the one that did the work (in Codex, a Codex collaboration agent). Self-review is not a substitute; the point is fresh eyes you cannot bring yourself. The subagent reads the audit trail and the run's transcript, then flags what the user should pay attention to: not a redo of the work, a scan for what's suboptimal or risky.

- Decisions logged with weak or absent evidence.
- Verification steps skipped or claimed without proof in the transcript.
- Choices that look risky in hindsight (premature, scope-creeping, papering over a symptom).
- Gaps the user would otherwise miss on a casual skim.

Every reply for a run that produced a trail has an "Attention" section, last before the reply's closing next step. Lead with the reviewer's model on its own line (`reviewed by <model>`), then list each flag pointing to specific rows or moments. "No flags" is a valid value; the model name is not. The self-audit asks if the log told the truth; this asks what the user should still scrutinize even when it did.

## Reviewing the trail

Read top to bottom, follow the evidence pointers, spot-check. `column -s$'\t' -t decisions.tsv` renders the log in a terminal. A row whose evidence doesn't resolve, or whose result is unverified, is the audit catching a gap.

## Composing this skill

Other skills route their audit trail here by name instead of inventing one, and let it own the format and columns.

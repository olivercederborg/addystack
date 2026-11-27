# fix-the-cause replays

Replays real sessions at the moment an agent picked a fix, to test the kit's
fix-the-cause-in-scope text (suite-audit R100 found the agents' first pick was the
symptom patch in 16 of 45 pushbacks). Each case's `CONTEXT.md` holds what that session
had verified by then, with the agent's own recommendation left out. The prompt is the
message the agent was answering.

| Case | Source | Right pick |
|---|---|---|
| `a8-sentry-digest` | T3 mcp:37eac4a4 (devbox) 2026-10-27 | keep the client digest events (regroup, tag), since dropping them loses error replays |
| `a9-third-party-noise` | T3 mcp:41985111 (devbox) 2026-10-27 | Sentry's third-party filter, not `denyUrls` for one script |
| `a2-receipt-first-resume` | T3 9b87d24b 2026-09-28 | name EXPORTED-before-uploads as the cause and weigh the checkpoint design against the brief's resume path |
| `b1-merge-queue-typecheck` | T3 4b06169e 2026-10-09 | work toward the cause, not a re-queue |
| `b2-run-ci-label` | T3 efd4aacb 2026-10-09 | `run-ci` now as a labelled stopgap, plus the workflow fix in its own PR off develop |
| `ctl-owner-elsewhere` (control) | T3 a1387e6c 2026-10-21 | hand the VAT block to Ander's DEV-2307 instead of building a parallel PR |
| `ctl-prod-hotfix` (control) | T3 b0da529d 2026-10-27 | ship the one-file hotfix now, with the runtime change kept out of option `a` |
| `ctl-scope-creep` (control) | T3 8575bceb (devbox) 2026-11-09 | no silent scope growth on #5634's card rule |

## Run

Each arm loads the kit text a live session loads: the router and principles index that
`~/.claude/CLAUDE.md` imports, with principle files behind the index's pointers. Build the
arms from addystack revisions, then start each trial with its arm's folder:

```sh
evals/fix-the-cause/arms.py . --check
evals/fix-the-cause/arms.py . /tmp/skill-evals/<change> current=origin/main new=<branch>
maintainer/evals.py start fix-the-cause-in-scope <id> /tmp/skill-evals/<change>/<arm>/t1 --variant /tmp/skill-evals/<change>/variants/<arm>
```

Then follow [the evals README](../README.md). Limit: `~/.claude/CLAUDE.md` still loads the
live router and principles index beside each arm's variant, so a `new` arm competes with
the live text it replaces. Two notes from R101:

- When a brief is too long to paste, give the player `Reply rules: on…` plus a pointer to
  the brief file. Then pass `replies --transcript` the player's own transcript, the one
  whose first user message is that pointer. A grep for the brief path also matches the
  parent's transcript.
- Grade one scenario's arms with one grader, from copies under neutral file names
  (`<id>-X.md`), since the trial path names the arm.

## R101 result (2026-11-10)

Claude Opus 5.5 (high) players and Codex gpt-6.1-sol (high) graders, one trial a side.
Arms: `current` (addystack `01412ea`) and `new` (`fix/fix-the-cause-default` at `9f95aad`).
A control holds when every assertion about its option `a` passes.

The recorded run used the corrected contexts and neutral side names, with
`evals.py record` on every grade. The command was
`evals.py table /tmp/skill-evals/r101b/sideB --against /tmp/skill-evals/r101b/sideA`,
with sideA as current and sideB as new:

| | current | new |
|---|---|---|
| Replays (5) | 9/15 | 10/15 |
| Option `a` picks the cause fix (replays) | 2/5 | 2/5 |
| ctl-owner-elsewhere | holds | holds |
| ctl-prod-hotfix | holds | **fails** |
| ctl-scope-creep | **fails** (#4) | **fails** (#4) |
| All assertions | 17/26 | 19/26 |

`new` names causes and compares fixes more often, but its picks match `current`. Both
arms fail ctl-scope-creep's #4, because their follow-up adds a connection metric to the card rule. On the
production hotfix it builds the Node 24 runtime PR alongside the hotfix. That failed in 2 of
3 trials (an earlier leaked-context trial failed, and one corrected-context trial held), so
the text didn't ship (D-r57). A typed fix kind on each pick failed that control twice too.

That run's preamble forbade reading files outside the variant, though the variant points
to the principle files; 13 of 16 players read the principle anyway. The preamble now
allows those files and rules out child tasks, and a9 and ctl-owner grade that nothing
was sent. The run's recorded grades, with the graders' quotes, are in
`~/.local/state/orchestrate/suite-audit/r101/r101b-run/`.

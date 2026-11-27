# approver-asked replays

Replays real sessions at the moment an agent decided whether to push a change that would
dismiss an approval on Oliver's PR. Suite-audit R115 found that agents price that push
against the change's severity ("a private type name isn't worth a second round of
approvals"), while Oliver prices it against who asked: an approver who asked for a small
change re-approves it quickly, and a follow-up PR needs a review of its own. He overrode
exactly the two cases where an approver asked for a change of 10 lines or fewer and the
agent offered a follow-up. Each case's `CONTEXT.md` holds what that session had verified
by then, with the agent's own pick left out. The prompt is the message the agent was
answering.

**A: build it here.** The right pick pushes to the approved PR.

| Case | Source | Right pick: Oliver's reply, with the option text it picked, or the R150 pick and his original one |
|---|---|---|
| `a-casper-rename` | T3 458beb27 2026-11-06 10:51 (PR-watch wake on #5614) | `b`, "rename now on #5614, push, re-request Casper" |
| `a-casper-lint-message` | T3 mcp:a0dc8ad7 2026-11-03 13:55 (address-review on #5551) | `a`, "fix, push (dismisses Casper's approval), post the reply, resolve". The agent got this one right; it guards against a regression |
| `ctl-notes-into-open-layer` | T3 1c846f92 (devbox) 2026-11-09 14:16 | since suite-audit R150, `a` builds Ander's two test notes in #5620, whose tests they cover. Oliver took "add all three to #5579, then draft replies to Ander" on 11-09, under the open-draft exit R150 removed; its id predates the move |
| `ctl-agent-sibling-fix` | T3 mcp:417ee644 2026-10-15 13:54 | since suite-audit R150, `a` fixes the three sibling tests on #5123: the same race in the same file, about two small commits. Oliver took a stacked #5127 on 10-15, under the keep-the-approval exit R150 removed; its id predates the move |

`build-now`'s `a-casper-waits` (T3 61f0be85, devbox, 2026-10-29: "just do it in this PR
since it will be approved quickly anyways") runs beside these.

**B: push nothing to the approved PR.**

| Case | Source | Right pick | Why |
|---|---|---|---|
| `ctl-reviewer-boundary` | T3 mcp:e1cdf2f4 2026-10-28 16:30 | no push to #5394–#5397: Oliver took the cleanup as a fifth layer, draft #5464 | Ander, the approver, titled his notes "cleanup PR to follow", and Oliver asked "just check if any of this makes sense to do as a follow-up" |

Since suite-audit R150 (2026-11-18) an approval doesn't decide a case: a fix the PR needs,
and an approver's ask, go in that PR even when the push dismisses its approvals. The
boundary case holds because Ander and Oliver set the boundary.

`build-now`'s `ctl-own-boundary` and `ctl-shared-pattern` controls run beside these. Its
`ctl-approval-preexisting` is a build-here case since R150.

`evals.json` holds each scenario's assertions, and `pick_assertions` names the one that
decides its pick.

## Run

Run each player isolated, with its own `CLAUDE_CONFIG_DIR` holding one addystack revision's
router, principles and every kit skill, as `build-now`'s R112 runs did:

```sh
maintainer/evals.py start approver-asked <id> /tmp/skill-evals/<change>/<arm>/t1
```

## R116 result (2026-11-11)

Arms, under neutral names: **G** current (addystack `a0bdaea`, origin/main); **H** slim-scope
only (`0dcbf7f`): a change waits only when it "would dismiss an approval for a change none
of the PR's approvers asked for", and a change an approver asked for "is built now, in
their PR or an open one above it"; **I** adds the index pointer "or deferring a change,
such as to keep an approval" and narrows "an open one" to "an open draft" (`a4a522d`); **J**
adds "including an approver's ask in their PR" to slim-scope's index line (`2e79971`,
addystack `fix/build-approver-asked-now`).

**Setup.** Claude Opus 5.5 (high) players, each run as `claude --print` with its own
`CLAUDE_CONFIG_DIR` holding one revision's router, principles and every kit skill (`git
archive`). All 160 players loaded their own arm's `CLAUDE.md`, made no tool call into the
live kit or another arm, read only their own arm's slim-scope exit, and only I and J
players carried the index pointer. Codex gpt-6.1-sol (high) graders, one per case: G, H
and I graded together (15 runs under shuffled labels), then J beside G's 5 runs (10
runs). That second grader's G counts matched the first on all 8 cases. 5 trials a case
and arm, at most 5 players or graders at once. Every grade is recorded with `evals.py
record`.

Each cell counts trials whose `pick_assertions` pass.

| case | current (G) | H | I | new (J) |
|---|---|---|---|---|
| build-now a-casper-waits | 0/5 | 0/5 | 1/5 | **5/5** |
| a-casper-rename | 4/5 | 1/5 | 4/5 | **5/5** |
| a-casper-lint-message | 4/5 | 5/5 | 5/5 | **5/5** |
| **A: build-here picks** | **8/15** | **6/15** | **10/15** | **15/15** |
| ctl-agent-sibling-fix | 5/5 | 5/5 | 5/5 | 5/5 |
| ctl-notes-into-open-layer | 5/5 | 5/5 | 5/5 | 5/5 |
| build-now ctl-approval-preexisting | 5/5 | 5/5 | 5/5 | 5/5 |
| build-now ctl-own-boundary | 2/5 | 4/5 | 4/5 | 4/5 |
| build-now ctl-shared-pattern | 5/5 | 5/5 | 5/5 | 5/5 |
| **B: holds** | **22/25** | **24/25** | **24/25** | **24/25** |

- **Reach decided it.** Players who opened slim-scope built Casper's change; those who
  didn't kept the approvals with a stacked follow-up. Players that read slim-scope: G 28,
  H 26, I 29, J 40 of 40. On a-casper-waits only 1 of 5 I players opened it, and that one
  built now; every J player opened it and built now.
- **H's rename misses:** three H runs put the rename in #5615, the approved layer above,
  which "an open one above it" allowed. "An open draft above it" closed that: no I or J run
  did it.
- **No over-building:** no control run pushed to an approved PR. One J run of
  `ctl-agent-sibling-fix` built the sibling fixes as a stacked draft, which is what Oliver
  took in the source thread.
- **ctl-own-boundary** misses keep the reason-check rule in the migration in every arm, as
  in R112. They aren't about approvals.
- **Assertion change:** the first grading of the two new A cases failed runs whose `a`
  pushed but left the reply to Casper as a draft. Messages to people are drafts, so the
  pick assertions were narrowed to building and pushing on the approver's PR, and both
  cases were regraded by fresh graders. Under the first wording, A was G 4/15, H 5/15, I
  3/15 (J wasn't graded under it).

**Verdict: ships** (D-r57). New makes 15/15 build-here picks against 8/15, and holds 24/25
controls against 22/25. Runner, briefs, logs, raw grades and the isolation proof are in
`~/.local/state/orchestrate/suite-audit/r116/iso/`; trial data in `/tmp/skill-evals/r116/`.

## R116 final-head replay (2026-11-11)

Review-loop round 1 on addystack#65 added a reviewer's own boundary as an exit ("or the
user or a reviewer set the boundary"), after J. Arm **K** (`59b4162`, the PR's head)
replayed the cases that change could move: the three A cases and `ctl-notes-into-open-layer`,
whose rename note Ander marked "for a follow-up". 20 isolated players, all 20 opened
slim-scope, isolation proof "180 players, 0 not isolated as expected". One blind grader
per case saw K's 5 runs beside G's 5, and again matched G's counts. verify-work's re-check
then replayed build-now's `a-retry-in-pr`, where leogenot's agent wrote "a follow-up for
both reasons is fine": 5 more isolated players, all opened slim-scope, graded by the
verifier rather than blind, with no G runs beside them.

| case | current (G) | final head (K) |
|---|---|---|
| build-now a-casper-waits | 0/5 | 5/5 |
| a-casper-rename | 4/5 | 5/5 |
| a-casper-lint-message | 4/5 | 5/5 |
| ctl-notes-into-open-layer | 5/5 | 5/5 |
| build-now a-retry-in-pr, replayed by verify-work's re-check and graded by it, not blind | — | 5/5 |

## R116 reviewer-boundary control (2026-11-11)

Review-loop round 3 found no replay guarded the reviewer-boundary exit. `ctl-reviewer-boundary`
replays Ander's "cleanup PR to follow" notes on an approved four-PR stack, and ran at G, J
(before the exit) and K (with it), 5 trials each, one blind grader over all 15.

| case | current (G) | J, without the reviewer exit | final head (K) |
|---|---|---|---|
| ctl-reviewer-boundary | 5/5 | 4/5 | 5/5 |

J's miss pushes the cleanup into the approved PRs: "Do now, in their PRs … fix notes 1–4
and the rename in-stack, then push". Oliver's own message also sets the boundary ("as a
follow-up"), so this case can't separate the reviewer exit from the user's; one trial is
the whole gap.

## R150 result (2026-11-18)

Suite-audit R150 removed slim-scope's "it would cost an approval for a change no approver
asked for" exit (addystack `fix/atomic-prs-fix-after-approval`): a fix the PR needs, a
carried-over gap in code it adds or rewrites included, goes in it even when the push
dismisses an approval, and `a` is that push, naming the dismissal. Oliver's rule, so a
single-arm check at the PR's head (`a38782a`), not an A/B. Isolated Claude Opus 5.5 (high)
players as in R116, one Codex gpt-6.1-terra (high) grader per case, recorded with
`evals.py record`.

| case | pick passes at `a38782a` |
|---|---|
| build-now ctl-approval-preexisting (now fix on #5153) | 5/5 |
| ctl-notes-into-open-layer (now #5620 only) | 5/5 |
| ctl-agent-sibling-fix (now fix on #5123) | 3/3 |
| build-now a-snoop-resubmit (guard: build now) | 3/3 |
| ctl-reviewer-boundary (guard: boundary holds) | 3/3 |

All 19 players opened the arm's own slim-scope and none read the live kit. A first run lost
isolation: R116's `build_cfg.py` kept the whole SessionStart group holding
`reply-shape-context.py`, which now also holds `skills-checkout-check.py`, and that rebuilt
the arm's `CLAUDE.md` back to the live router. Keeping only the reply-shape hooks fixed it.
verify-work's trim of slim-scope's Atomic PRs paragraph (`5a4186f`, the PR's final head)
came after; ctl-approval-preexisting, rerun there, passed 5/5 again. Before the "carried-over gap" wording, ctl-approval-preexisting passed 3/5: two players
deferred because the gap "predates #5153". Runner, logs, grades and the isolation proof
are in `~/.local/state/orchestrate/suite-audit/r150/iso/`; trial data in
`/tmp/skill-evals/r150/`.

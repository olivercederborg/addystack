# build-now replays

Replays real sessions at the moment an agent decided whether to build a change now or
later, to test the kit's deferral text. Suite-audit R111 found that of 12 deferrals Oliver
overrode, 10 cost only size, scope, or zero exposure to build now. Each of the 15 he
accepted had a concrete cost: someone else owns it, it can't be built yet, it dismisses an
approval for an unasked change, or he set the boundary. Each case's `CONTEXT.md` holds what
that session had verified by then, with the agent's own recommendation left out. The prompt
is the message the agent was answering.

None of these cases comes from a Sentry alert, and they measure deferral, not
patch-versus-cause, so `fix-the-cause`'s verdicts don't carry over.

**A: build now.** Oliver overrode a deferral, or, where a row says so, suite-audit R150's
rule builds what he deferred.

| Case | Source | Right pick: Oliver's words, or the R150 pick and his original one |
|---|---|---|
| `a-noton-rule` | T3 1c846f92 (devbox) 2026-11-09 14:29 | "but isnt it the best long term solution ?": build the not-on rule in draft #5579, pre-launch. He had already picked "hide Projekt on top-up rows in #5579 now" at 13:03 |
| `a-hide-projekt` | T3 1c846f92 (devbox) 2026-11-09 13:01 | `b`, "hide Projekt on top-up rows in #5579 now" |
| `a-snoop-read-sync` | T3 8f91d657 2026-10-18 21:15 | `b`, "sync read state through the server in this milestone" |
| `a-snoop-resubmit` | T3 fb5acb38 2026-10-28 | "just do the best long-term fix": resubmit on a transient ElevenLabs failure, in #132 |
| `a-inbox-trigger-by-id` | T3 636dc30b (devbox) 2026-11-05 13:45 | "lets just fix it now? find the best and most idiomatic long-term fix and open a PR" |
| `a-casper-waits` | T3 61f0be85 (devbox) 2026-10-29 10:17 | "just do it in this PR since it will be approved quickly anyways" |
| `a-retry-in-pr` | T3 f8e28717 2026-09-30 13:05 | "lets include the retry fix in this PR", with item 8 (the repository move) still deferred |
| `ctl-approval-preexisting` | T3 096254a3 (devbox) 2026-10-20 14:24 | since suite-audit R150: fix cubic's finding on #5153 and push, since the gap is in the action #5153 adds. Oliver deferred it on 10-20 to keep Ander's approval, under the exit R150 removed; its id predates the move |

`ctl-approval-preexisting`'s R150 result is in `approver-asked`'s README.

`a-noton-rule` and `a-hide-projekt` share a thread, so count them as one observation and a
half, not two.

**B: deferring is right.** Oliver accepted the deferral.

| Case | Source | Right pick | The cost of building now |
|---|---|---|---|
| `ctl-own-boundary` | T3 367329d6 2026-11-03 13:52 | `a`, "keep the migration minimal; the cleanups become follow-ups" | Oliver set the boundary: "We want to keep the scope quite minimal just for the migration and then we can clean up even more later on as follow-ups" |
| `ctl-shared-pattern` | T3 d9259eab 2026-11-04 12:39 | `a`, "log a follow-up, end the loop, then mark #5576 ready" | an undesigned interface change in a pattern 25 test files share |

`evals.json` holds each scenario's assertions, and `pick_assertions` names the ones that
decide its pick: a build-now pick for an A case, a hold for a B case.

## Run

Build the arms as `fix-the-cause` does, under neutral names, then start each trial:

```sh
evals/fix-the-cause/arms.py . /tmp/skill-evals/<change> X=origin/main Y=<branch>
maintainer/evals.py start build-now <id> /tmp/skill-evals/<change>/<arm>/t1 --variant /tmp/skill-evals/<change>/variants/<arm>
```

The `--variant` route still loads the live router beside the arm's text. For a clean
comparison, run each player with its own `CLAUDE_CONFIG_DIR`, as R109's isolated rerun did;
see the R112 result below.

## R112 result (2026-11-10)

Arms: current (addystack `78119c0`, origin/main) and new (`fix/build-right-shape-now` at
`6105711`): slim-scope names the only reasons a change waits, check-exposure's "Optional
at most" becomes "now is the cheapest time", and fix-the-cause, scope-grill, build,
address-review and the router point at slim-scope. Net words 6723 → 6717.

**Setup.** Claude Opus 5.5 (high) players, isolated as in R109: each ran as
`claude --print` with its own `CLAUDE_CONFIG_DIR`, holding the arm's router, principles,
and its own copies of scope-grill, build and address-review. All 60 players loaded their
arm's `CLAUDE.md`, none loaded a live path, and the new index phrase appeared once in every
new player and never in a current one. Codex gpt-6.1-sol (high) graders, one per case,
graded all 6 runs of that case under shuffled labels. 3 trials a case, at most 5 players or
graders at once. Every grade is recorded with `evals.py record`.

Each cell counts trials whose `pick_assertions` pass. Failing assertions are in brackets.

| case | current | new |
|---|---|---|
| a-noton-rule | 3/3 | 3/3 |
| a-hide-projekt | 0/3 (t1#2, t2#2, t3#2) | 1/3 (t1#2, t2#2) |
| a-snoop-read-sync | 0/3 | 0/3 |
| a-snoop-resubmit | 2/3 (t2) | 3/3 |
| a-inbox-trigger-by-id | 2/3 (t1) | 2/3 (t2) |
| a-casper-waits | 0/3 | 1/3 |
| a-retry-in-pr | 3/3 | 3/3 |
| **A: build-now picks** | **10/21** | **13/21** |
| ctl-own-boundary | 3/3 | 3/3 |
| ctl-approval-preexisting | 3/3 | **2/3** (t3#2) |
| ctl-shared-pattern | 3/3 | 3/3 |
| **B: holds** | **9/9** | **8/9** |
| All assertions | 55/69 | 59/69 |

- **a-hide-projekt**: every run in both arms hid Projekt on top-ups in #5579 now. The five
  failures cite only Omkostningstype, which the assertion then named and Oliver's pick
  didn't; the assertion now grades Projekt alone. Counted that way, A is current 13/21
  against new 15/21.
- **The new arm's control failure**: in ctl-approval t3, its `a` was "defer, build the fix
  as a draft follow-up PR, reply to cubic". It kept Ander's approval but built the change
  now, in a separate PR. The rule's "waits for a one-line follow-up" read as "build it
  elsewhere".
- **What moved**: a-snoop-resubmit (3/3 against 2/3) and a-casper-waits (1/3 against 0/3).
  On Casper's comment, five of six runs still stacked a follow-up PR to keep the
  approvals, though the approver had asked for the change.
- **What didn't**: no run in either arm synced snoop read state in the milestone. They kept
  per-device read state because the option carried a migration ("hard to undo"), and
  because Oliver is the only pilot user. a-noton-rule passes in every run of both arms:
  its context carries Oliver's 13:03 build-now pick and the agent's own 13:19 "the
  long-term fix", which the original session had in a longer thread.

**Verdict: no change** (D-r57). New makes more build-now picks (13 against 10, or 15
against 13 on Projekt alone), but a B case failed in one trial, and the bar needs every B
trial to hold. Runner, briefs, logs, raw grades and the isolation proof are in
`~/.local/state/orchestrate/suite-audit/r112/iso/`; trial data in `/tmp/skill-evals/r112iso/`.

## R112 rerun (5 trials, 2026-11-11)

The new arm was revised at `6dd0e1e` so a change that waits stays unbuilt: "Then it's a
one-line follow-up, unbuilt in this run: no separate or stacked PR unless asked." Net words
stay at 6717. The rerun used fresh trials against current (`78119c0`), 5 per case and arm,
with the same isolation and grading as above. Graders saw all 10 runs of a case under
shuffled labels. All 100 players loaded their own arm's `CLAUDE.md` and no live path, and
the new phrase appeared once in every new player and in no current one. The run used the
corrected a-hide-projekt assertion.

| case | current | new |
|---|---|---|
| a-noton-rule | 5/5 | 5/5 |
| a-hide-projekt | 5/5 | 5/5 |
| a-snoop-read-sync | 0/5 | 1/5 |
| a-snoop-resubmit | 2/5 | 4/5 |
| a-inbox-trigger-by-id | 4/5 | 5/5 |
| a-casper-waits | 0/5 | 0/5 |
| a-retry-in-pr | 5/5 | 5/5 |
| **A: build-now picks** | **21/35** | **25/35** |
| ctl-own-boundary | 3/5 (t1, t4) | **4/5** (t5) |
| ctl-approval-preexisting | 5/5 | 5/5 |
| ctl-shared-pattern | 5/5 | 5/5 |
| **B: holds** | **13/15** | **14/15** |
| All assertions | 93/115 | 103/115 |

- **The revision fixed what it aimed at**: ctl-approval held in all 5 new trials. None
  built cubic's fix in a separate PR.
- **ctl-own-boundary fails in both arms, and the case is the cause.** Its `CONTEXT.md`
  lists "`oxlint-disable` with a required reason" as the third round-3 cleanup. In the
  original thread, converting the 79 comments was needed either way, and only the
  reason-check rule became a follow-up. New t5 and current t1 kept the reason rule in the
  migration, which is a real miss. Current t4 converted the comments and made the rule a
  follow-up, which matches Oliver's accepted plan, and still failed. Fixing this case means
  separating the comment conversion from the reason rule in its context and assertion, then
  replaying it.
- **What moved**: a-snoop-resubmit (4/5 against 2/5), a-inbox (5/5 against 4/5), and the
  first synced read state (1/5 against 0/5).
- **What didn't**: a-casper-waits is 0/10. Every run kept both approvals by stacking a
  follow-up, though the approver asked for the change. The rule's approval exit ("an
  approval for an unasked change") didn't reach that pick.

**Verdict: no change** (D-r57). New makes 4 more build-now picks, but the bar needs all
15 B trials to hold, and new held 14. Its one miss is in the case that current also fails
twice. Files are in `~/.local/state/orchestrate/suite-audit/r112/iso2/` and
`/tmp/skill-evals/r112b/`.

## ctl-own-boundary fix and replay (2026-11-11)

**Changing a case after seeing results is a risk**: it can turn a loss into a pass. So the
fix follows only the original thread (T3 367329d6). Before the pick, round 2 said "The 79
`eslint-disable` lines naming moved rules would be reported as unused by ESLint, which no
longer runs those rules." In the plan Oliver accepted with `a` at 13:54, the conversion
stayed: "Disable comments for moved rules: they become `oxlint-disable … -- reason`,
keeping the reason text. This rename is needed either way, because ESLint would report the
old comments as unused". Only the rule became a follow-up: "5. Add a Franklin rule that
requires a reason on `oxlint-disable`. Until then, reasons are kept but not enforced."

The context now keeps the comment conversion in the migration and lists the reason-check
rule as the third round-3 cleanup. The deciding assertion counts that rule as a cleanup and
leaves the conversion out of the decision. The case was replayed alone with 5 fresh trials
per arm, isolated as before (10/10 players proven), and graded by one blind grader seeing
all 10 runs.

| | current | new |
|---|---|---|
| ctl-own-boundary (replay) | 4/5 (t2) | 4/5 (t2) |

Both misses keep the reason-check rule in the migration, which Oliver's plan made follow-up
5, so they're real misses. With the other 9 cases' rerun grades:

| | current | new |
|---|---|---|
| A: build-now picks | 21/35 | 25/35 |
| B: holds | 14/15 | 14/15 |

**Verdict: no change** (D-r57). New makes 4 more build-now picks but holds 14 of 15 B
trials, and the bar needs all 15. R112 is a no-change record. Files are in
`~/.local/state/orchestrate/suite-audit/r112/iso3/` and `/tmp/skill-evals/r112c/`.

**Decision (2026-11-11).** Oliver accepted the result as a win: more A picks in both runs,
and B equal to current at 14/15, since the absolute "all 15 hold" bar was stricter than
current itself meets. The rule is open as addystack#62.

## Final-head replay (addystack#62 at `82d35a6`, 2026-11-11)

verify-work found that the shipped text had changed since the measured `6dd0e1e`. The
changes: slim-scope's Apply-when line now names deferring a change, `format.md` rates a
finding nobody can hit "Cleanup at most" and says it needs no shim, the verifier's
no-caller control was narrowed, and the router edit was reverted. So the new arm was rerun
at `82d35a6`: 5 trials × 10 cases, isolated (50/50 proven). Each case was graded by one
blind grader that saw these 5 runs beside current's 5 rerun runs (r112b, and r112c for
ctl-own-boundary) under shuffled labels.

| case | current | new at `82d35a6` |
|---|---|---|
| a-noton-rule | 5/5 | 5/5 |
| a-hide-projekt | 5/5 | 5/5 |
| a-snoop-read-sync | 0/5 | 0/5 |
| a-snoop-resubmit | 2/5 | 5/5 |
| a-inbox-trigger-by-id | 4/5 | 4/5 |
| a-casper-waits | 0/5 | 0/5 |
| a-retry-in-pr | 5/5 | 5/5 |
| **A: build-now picks** | **21/35** | **24/35** |
| ctl-own-boundary | 4/5 | **2/5** |
| ctl-approval-preexisting | 5/5 | 5/5 |
| ctl-shared-pattern | 5/5 | 5/5 |
| **B: holds** | **14/15** | **12/15** |

All three new ctl-own-boundary misses keep the reason-check rule in the migration on
build-now grounds, against Oliver's "keep the scope quite minimal". One example: "Adding it
later still costs the same ≈3 files, plus a sweep". New at `6dd0e1e` missed that case once
in 5. The text change most likely to matter is the Apply-when line, which sends a deferral
decision to slim-scope. With 5 trials, 2/5 against 4/5 may still be noise. Even so, B is
now below current, which breaks the condition Oliver's ship decision rested on.

Harness note (verify-work finding 8): this replay's arm took only scope-grill, build and
address-review from `82d35a6`. Every other skill, review-loop included, came from the live
`78119c0` kit. So the ctl-shared-pattern runs that loaded review-loop read the base's
"Optional at most" and "skip: unreachable" lines, not the head's. That case scored 5/5 in
both arms. A next replay should take every skill the diff touches from the head.
Files are in `~/.local/state/orchestrate/suite-audit/r112/iso4/` and `/tmp/skill-evals/r112d/`.

## Control check: ctl-own-boundary, 10 trials per arm (2026-11-11)

This tests whether the final-head drop (2/5) was noise or caused by slim-scope's new
Apply-when line. Three arms ran, each loading every kit skill (review-loop and the format
copies included) from its own revision, which fixes verify-work's finding 8:

- current, `78119c0`
- head, addystack#62 at `82d35a6`
- head-no-apply, scratch ref `refs/r112/head-no-apply`: `82d35a6` without the Apply-when
  line

30 isolated players were checked by grep. All loaded their own arm's `CLAUDE.md` and skills
path, none loaded another arm's, and no tool call read the live kit. One blind grader saw
all 30 runs under shuffled labels.

| Arm | Holds (10 trials) | Pooled with earlier same-text trials |
|---|---|---|
| current | 9/10 | 13/15 (+ r112c 4/5) |
| head `82d35a6` | **10/10** | 12/15 (+ r112d 2/5) |
| head-no-apply | 8/10 | — (no earlier run at this text) |

The misses state their own reasons:

- current t7: "ESLint keeps requiring a reason through an option, so no new rule"
- head-no-apply t2: "The reason rule keeps a check Franklin has today"
- head-no-apply t7: "Moving the disable comments to `oxlint-disable` takes them out of
  ESLint's reason check, and oxlint can't require a reason itself"

Every miss in this check keeps reason enforcement to preserve today's check, in the current
arm too, and none cites build-now. The earlier 5-trial replay's three head misses did. Head
is within one trial of current here, and the Apply-when line isn't the cause: removing it
held 8/10. The earlier 2/5 isn't explained: same text, but a different grader and different
miss reasons, and 2/5 against 10/10 is unlikely by chance alone (one-sided Fisher p ≈ 0.02).
The pooled counts are the fair summary: head 12/15, current 13/15.
Files are in `~/.local/state/orchestrate/suite-audit/r112/iso5/` and `/tmp/skill-evals/r112e/`.

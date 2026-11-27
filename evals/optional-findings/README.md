# optional-findings replays

Replays real sessions at the moment verify-work or review-loop reported findings, to test
the kit's **Optional** severity: whether a right, in-scope fix with a real cost gets built
in this change, while a true nicety still waits. Suite-audit R113 mined Oliver's Mac and
devbox threads for replies that carried an Optional finding (233 pairs) and what he
answered. Each case's `CONTEXT.md` holds the findings that session had checked, with their
severity and call left out, so the player sets both. The prompt is the message the report
answered.

**A: build now.** Oliver had an Optional finding built that the agent's option `a` left.

| Case | Source | Right pick, in Oliver's words |
|---|---|---|
| `a-read-scope` | T3 510cef73 2026-10-16 15:01 (verify-work on draft #5151) | `b`, "also fix 5": apply the read scope in `update` |
| `a-upload-cache` | T3 4904605c 2026-10-14 11:38 (review-loop on drafts #5083/#5084) | `b`, "also delete the cached upload copy after the upload finishes (4)" |
| `a-idiom-pass` | T3 1c846f92 (devbox) 2026-11-04 17:53 (verify-work on draft #5612) | "Do this and then look for any other improvements that can be made to make it as Effect-idiomatic as possible": the repeated `Loaded` check became `Catalog.items` |
| `a-crashed-sweep` | T3 f8e28717 2026-09-29 09:28 (review-loop round 2 on #4567) | "should we fix the optionals?", then "fix both + push" |

**B: waiting is right.** Oliver accepted leaving the finding unbuilt.

| Case | Source | Right pick | Why it waits |
|---|---|---|---|
| `ctl-zero-hits` | T3 9e85c02a 2026-10-18 14:56 | none of the five, after "are the 5 optionals worth doing?" | #74 is merged, and 60 days of sessions show almost no real hits |
| `ctl-loud-test` | T3 44592a29 2026-09-25 01:26 | "drop it then", after "is it worth addressing?" | the missing test guards a rare case that already fails loudly through a tested guard |

`build-now`'s three controls (`ctl-own-boundary`, `ctl-approval-preexisting`,
`ctl-shared-pattern`) run beside these, since the severity text reaches scope-grill,
address-review and review-loop too.

`evals.json` holds each scenario's assertions, and `pick_assertions` names the one that
decides its pick.

## Run

Run each player isolated, with its own `CLAUDE_CONFIG_DIR` holding one addystack revision's
router, principles and every kit skill, as `build-now`'s R112 runs did:

```sh
maintainer/evals.py start optional-findings <id> /tmp/skill-evals/<change>/<arm>/t1
```

## R113 result (2026-11-11)

Arms: current (addystack `c0ab2c3`, origin/main) and new (addystack #64,
`fix/build-optional-findings-now` at `19358a5`): Optional now means "a nicety with no correctness or maintenance cost", a
finding with either cost is a Blocker or Cleanup fixed in the change unless the slim-scope
principle says it waits, review-loop's reviewer prompt says the same, and verify-work's
re-check drops its "hand one back only for a real risk" clause, which the new definition
covers.

**Setup.** Claude Opus 5.5 (high) players, each run as `claude --print` with its own
`CLAUDE_CONFIG_DIR` holding one revision's router, principles and every kit skill (`git
archive`), under neutral arm names. All 90 players loaded their own arm's `CLAUDE.md`, made
no tool call into the live kit or the other arm (the only live path any touched is the
skills' Notes probe `ls ~/.local/state/addystack/notes/`, a folder that doesn't exist on
this machine), and the 24 new players that read a format copy read only the new
definition, the 28 current ones only the old. Codex gpt-6.1-sol (high) graders, one per
case, graded all 10 runs of that case under shuffled labels. 5 trials a case and arm, at
most 5 players or graders at once. Every grade is recorded with `evals.py record`.

Each cell counts trials whose `pick_assertions` pass. Failing trials are in brackets.

| case | current | new |
|---|---|---|
| a-read-scope | 5/5 | 5/5 |
| a-upload-cache | 0/5 (all) | **4/5** (t3) |
| a-idiom-pass | 4/5 (t4) | 3/5 (t3, t4) |
| a-crashed-sweep | 5/5 | 5/5 |
| **A: build-now picks** | **14/20** | **17/20** |
| ctl-zero-hits | 3/5 (t2, t5) | 4/5 (t2) |
| ctl-loud-test | 1/5 (t1, t2, t4, t5) | 2/5 (t2, t3, t5) |
| build-now ctl-own-boundary | 3/5 (t1, t3) | 5/5 |
| build-now ctl-approval-preexisting | 5/5 | 5/5 |
| build-now ctl-shared-pattern | 5/5 | 5/5 |
| **B: holds** | **17/25** | **21/25** |
| all assertions | 80/95 | 87/95 |

**Verdict at `19358a5`: ships (D-r57).** The final head is judged in the next section. New
makes 3 more build-now picks, and no control holds fewer
times than under current. Player cost: current $15.50, new $16.40, medians 57 s and 61 s.

- **What moved:** a-upload-cache, the cache copy every upload leaves behind. All 5 current
  runs called it a follow-up for #5084's Not in scope line; 4 of 5 new runs fixed it in the
  stack. The one new miss called it "a design change for a nicety".
- **Ceilings:** a-read-scope and a-crashed-sweep pass 10/10. `format.md`'s "Cleanup at most"
  for a finding nobody can hit (addystack #62) already moves the read-scope hole into the
  fix list, so neither separates the arms.
- **a-idiom-pass** went 4/5 to 3/5. The new misses still labelled the twice-written check
  Optional because it gives "the right result today", though it's duplication; one trial
  is within noise.
- **ctl-loud-test fails in both arms** (4/5 and 3/5 add the test). Both arms' reviewer prompt
  already calls "a changed line no test protects" a Cleanup, and Oliver's "drop it then"
  rested on the duplicate guard failing loudly. The case measures that call, which the new
  text doesn't touch, so it can't show harm here or help.
- **ctl-own-boundary** 3/5 to 5/5 is the same swing R112 saw on this case (2/5 to 10/10),
  not something the severity text explains.

**Limits.** 5 trials; the A gain rests mostly on one case. One grader saw all 10 runs of a
case. Players ran outside T3 with only the reply-shape hooks. Contexts compress the source
threads, and a-upload-cache's "a" prompt is the pick that started the review round.

## R113 final head (`1398afe`)

verify-work and a 3-round Codex review-loop changed the text after the run above: Optional
became "what can wait outside the agreed outcome: a nicety with no correctness or
maintenance cost, or a fix the slim-scope principle says waits", and "any other cost the
change caused or worsened is a Blocker or Cleanup, fixed in this change". verify-work's step
2 counts "a maintenance cost it adds, such as logic it writes twice" as Cleanup evidence,
review-loop's reviewer prompt matches, and verify-work's security hand-back is restored. So
the shipped text was replayed: 45 fresh isolated players at `1398afe` (arm L), each case
graded by a new blind grader beside the current arm's 5 runs above, regraded. A replay
started at `a16aeda` was stopped when verify-work changed the text again; its 14 finished
runs were set aside unscored.

| case | current | final head |
|---|---|---|
| a-read-scope | 5/5 | 5/5 |
| a-upload-cache | 0/5 | **5/5** |
| a-idiom-pass | 4/5 (t4) | **5/5** |
| a-crashed-sweep | 5/5 | 5/5 |
| **A: build-now picks** | **14/20** | **20/20** |
| ctl-zero-hits | 3/5 (t2, t5) | 3/5 (t1, t4) |
| ctl-loud-test | 1/5 | 0/5 |
| build-now ctl-own-boundary | 3/5 (t1, t3) | 3/5 (t3, t5) |
| build-now ctl-approval-preexisting | 5/5 | 5/5 |
| build-now ctl-shared-pattern | 5/5 | 4/5 (t1) |
| **B: holds** | **17/25** | **15/25** |
| all assertions | 80/95 | 85/95 |

B came out 2 lower, so the two controls that dipped got 10 more trials per arm (t6-t15),
graded by one blind grader per case over 20 shuffled runs. This is extra sampling after
seeing a result, so both counts are given.

| control | current, 5 + 10 | final head, 5 + 10 |
|---|---|---|
| ctl-loud-test | 1/5 + 3/10 = 4/15 | 0/5 + 3/10 = 3/15 |
| ctl-shared-pattern | 5/5 + 8/10 = 13/15 | 4/5 + 9/10 = 13/15 |
| **B pooled, all 5 controls** | **28/45** | **27/45** |

- **No sign the final text over-builds.** On ctl-shared-pattern, current built the
  undesigned shared-pattern change now in 2 of 15 runs, the final head in 0. The final
  head's 2 misses dropped the finding instead of keeping a follow-up. On ctl-loud-test,
  both arms add the test in most runs (current 11/15, final head 12/15), citing slim-scope's
  "now is the cheapest time" in both.
- **Verdict at the final head:** A 20/20 against 14/20; B pooled 27/45 against 28/45, one
  trial apart. That clears the bar if "no worse" allows R112's noise rule (current − 1), and
  misses it read strictly.
- **Cost:** final-head players $13.84 (median 60 s), control check $10.64.

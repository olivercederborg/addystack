---
name: maintain-verification-skill
description: Audit a project's verify-<app> skill and feature map against the source and the live app, then ship one PR of proven corrections.
disable-model-invocation: true
metadata:
  layer: optional
---

# Maintain a verification skill

The unit of rigor is the feature, not every sentence.

## Outcomes

End on exactly one, and say which:

- **clean**: every feature got source and live coverage, and nothing needs fixing. No
  branch, no PR.
- **changed**: one PR ships proven doc, map, or harness corrections.
- **blocked**: coverage couldn't finish, or a proven fix couldn't ship safely. Name what
  blocked it.

## Edit scope

Edit only the verification skill's own folder: its `SKILL.md`, `features/`, and the
scripts it owns. Product code stays untouched for the whole run. When the app no longer
does what the map describes, sort it as **drift** or a **product gap** (step 6).

## 1. Locate the target

The target is the repo policy's `verifySkill` (`<kit>/bin/addystack policy --repo
<checkout>`). With none set, find the project-local skill with launch, doctor, and drive
sections and a feature map, usually `.agents/skills/verify-*/` or
`.claude/skills/verify-*/`; a folder reached through a link counts once. Several
candidates: ask which. None: stop, and offer to create one from the project's existing
UI test setup.

Work in a fresh worktree off the default branch (fetched first), so the map is checked
against the code that shipped, and the user's checkout stays on its branch. When git
tracks nothing in the skill's folder, there is no PR: work in the checkout that holds
it, and back up the folder before the first edit. When git tracks it but an ignore rule
still matches a new file there (`git check-ignore -v <folder>/new.md`), add each new
file with `git add -f`, and report the rule.

**Done when:** the target, its feature map, and the worktree or backup path are named.

## 2. Index hygiene

Read the feature map's README and list its sibling files. Fix missing, extra, duplicate,
or dead entries, and note each feature that has no recipe.

**Done when:** the README's table and the files on disk match one to one.

## 3. Source wave

Start one read-only subagent per feature file, all at once, through `orchestrate`. Each
reads how the user-facing feature works from source and returns: feature summary · source
entry points · likely drift with `path:line` citations, or none. Subagents never drive
the app and never edit files.

**Done when:** every feature file has a returned summary.

## 4. Reconcile

- **Drift**: spot-check each cited drift against the source. Leave clean claims alone.
- **States**: merge overlapping recipes into as few app states as practical.
- **Churn**: sweep the last 30 days of commits, busiest folders first, for user-facing
  surfaces the map lacks. A surface counts as missing only with a concrete source path.

**Done when:** each drift claim is confirmed or dropped, and each missing surface has its
source path.

## 5. Live pass

Required even when the source looks clean. You own all driving, serially, following the
skill's own launch model. When another agent's run holds the app or device, or waits in
line for it, wait until both are done; their runs and sessions stay untouched. Steps 3
and 4 need no device, so do them first. Exercise every feature at least once. First run
every shipped recipe as it stands, before changing any, and record each result: this
baseline shows which findings ordinary use would already catch. A feature with no recipe
gets one, written and proven the way the skill's drive section says: that is a harness
gap fixed under edit scope.

Hold three invariants for the whole pass, whatever fails:

1. **Doctor first.** Drive only an instance that passed doctor since it last surprised
   you: before the first drive, and again after any failed drive. When doctor can't see
   the failure (a stuck screen on a healthy process), reset or relaunch.
2. **Evidence survives.** Everything captured so far is still at its named location after
   every cleanup. Check the path.
3. **Nothing outlives its drive.** A failed drive's leftovers are cleaned up, whether the
   session is stuck, exited, or shared. On a shared instance, clean the leftovers, not the
   instance.

A doctor failure caused by skill drift is drift: fix it, restart what the fix
invalidated, and retry once before calling the pass blocked. A feature that can't be
reached is **unreachable** only with the concrete prerequisite (auth, entitlement, OS,
device, external state) and the route tried. A prerequisite the map omits is drift. Run
the skill's cleanup after the last drive, including re-proofs.

**Done when:** every feature is verified or unreachable with its prerequisite, cleanup
has run, and the evidence is in place.

## 6. Triage

Sort every finding into one kind. A fix's live proof is another drive in step 5, under
its invariants.

- **Drift**: a wrong or missing user-facing description. Fix it.
- **Harness gap**: working behavior the recipes can't drive. Fix it, keep scripts
  executable, document how to run them in the skill, and drive the fix live before it
  ships. A fix to a shared helper re-drives every recipe that uses it.
- **Product gap**: app behavior that's broken. Report it to the user, outside the PR.

**Done when:** every finding has a kind, and every fix to ship has a live proof.

## 7. Ship or stop

- **changed**: re-read every changed file, commit each correction on its own, and open
  one PR with `open-pr` through the repo's tooling. For a git-ignored skill, report the
  changed paths and the backup instead.
- **clean** or **blocked**: no PR. Report the outcome and the coverage.

Keep run notes (features covered, unreachable prerequisites, confirmed drift, outcome) in
the run's scratch folder, outside the repo.

The outcome is the headline. What changed and each product gap, as a **Decide** note,
are the notes, and the coverage table and the checks go in the fold.

```markdown
🟡 **#61 fixes 2 drifts and adds 1 recipe; 1 product gap found.**

- The skill now drives Restart recovery, and Analyze's label matches the app.
- **Decide**: Analyze crashes on an empty week. Pick: track it as an issue, outside #61.

<details><summary>Coverage and checks: ⚠️ 1 unreachable · ✅ 9/9 features driven</summary>

| Feature | Source | Live | Result |
|---|---|---|---|
| Quick Session | ✅ | ✅ | current |
| Analyze | drift | ✅ | label fixed · `a1b2c3d` |
| Restart recovery | ✅ | ✅ new recipe | `d4e5f6a` |

⚠️ Live Activity unreachable: needs a physical iPhone · ✅ 9/9 features driven ·
✅ cleanup left evidence in /tmp/verify-strict/current

</details>
```

**Done when:** the outcome is named, and a changed run has its PR link or changed paths.

Adapted from Lauren Tan's `maintain-verification-skill` in pstack (MIT); see
[NOTICE](NOTICE).

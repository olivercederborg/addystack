---
name: babysit
description: "Keeps the user's open PR or stack moving: restacks, handles review threads, fixes CI, pushes, replies, and keeps the watch while the PR waits on reviewers. Use on a `watch_pull_request` wake on the user's own PR, or when asked to babysit a PR."
compatibility: Requires git, gh (authenticated), gh stack, jq, and T3 Code's `watch_pull_request`.
metadata:
  layer: orchestrator
---

# Babysit

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

A watch wake is news, not an order. Each wake runs one pass over the PR or stack:
collect every fix, push once, then reply against the pushed head. The pass ends at
**maintenance done**, or with each unfinished PR watched while CI runs. A wake that
changes nothing, such as a Vercel, Graphite, or Linear comment, or a green check while
a required one still runs, with no person's comment, fix, or watch to start, is a quiet
watch wake: its reply is the turn block alone, in a ◆ coordinator thread the
card on screen's while the queue holds one.

`watch_pull_request` wakes the thread when a check fails, the required checks pass,
someone else comments or reviews, or the branch starts to conflict. Only comments
posted after the call wake it, so before starting a watch, run one pass on the feedback
already there.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Calls here: address-review's **Fix**, **Decline**, **Defer**, **No change**, plus
**Rerun** for a flaky check and **Restack** for a stale base.

## Example turn (illustrative: match the shape, not the content)

````markdown
🟡 **[#212, Publish retried exports](https://github.com/acme/app/pull/212) maintained: a retried export publishes again.**

- **Review**: my reply declining @sam's per-retry log, below. Approval posts it.

> <sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
> Leaving this out. The task runner already logs each retry with its attempt number.

<details><summary>Checks: ✅ 4 passed · 2 threads handled · watch removed</summary>

✅ required checks green on `c41d2e0` · ✅ threads 2/2 handled · ✅ no conflicts · ✅ idioms (the repo's lenses, grounding, taste)

- **1** · CI `test` and cubic · a retry publishes nothing · `export.ts:9` → Fix · `c41d2e0`
- **2** · @sam · log each retry? · `export.ts:12` → Decline: the task runner logs retries

Patch-id changed: verify-work done, review-loop clean.

</details>
````

## 1. Read the wake

- **Scope**: the PR the wake names. In a stack, every open PR in it
  (`gh stack view`), worked from the lowest unmerged PR up, since a fix below
  restacks everything above.
- **Fetch** each PR with `scripts/github.sh threads N` and `feedback N`
  ([GitHub commands](references/github.md)).
- **Conflicts**: read each PR's merge state from `scripts/github.sh mergeable N`.
  `DIRTY` means it conflicts with its base. A draft prints it too, as in
  `merge state once ready: DIRTY`.
- **Trust**: the repo policy's `trust`, as [workflow.md](references/workflow.md) defines it.
- **Patch-ids**: record each PR's patch-id and verdict with `scripts/github.sh target N`,
  which fetches and hashes the diff as the merge gate does.

**Done when:** every PR in scope has its threads, checks, and conflict state fetched,
and each layer's patch-id is recorded.

## 2. Collect every fix

Push nothing in this step. Work the lowest PR first, in this order:

1. **Conflicts.** Restack with `scripts/stack.sh restack`, as address-review's step 3
   does.
2. **Review threads.** Run address-review's steps 1 and 2 (fetch, triage), verifying
   each claim with [grounding](references/grounding.md), then fix as under
   **Code fixes**.
3. **CI**, for each failing check, with its log from
   `gh run view <run-id> --log-failed`:
   - **Outside the diff**: run `git fetch origin <default>`, then check for a stale base
     with `git merge-base --is-ancestor origin/<default> <lowest branch>`. A false result
     means the base moved: **Restack** with `scripts/stack.sh restack`, and let CI rerun on the
     push. When the base is current and fails the same way, the failure isn't this
     PR's. Report it, and keep the watch.
   - **Flaky** (a timeout, a network error, a runner crash): **Rerun** once with
     `gh run rerun <run-id> --failed`. An identical second failure is real.
   - **Waiting on outside state** (a linked issue, a label another service sets): make
     the state land, such as re-saving the PR body so Linear re-reads its link, then
     **Rerun** once. A second identical failure on a later wake is real: report it.
   - **Real**: a code fix.

**Code fixes.** With autonomy under **Approval**, fix each one yourself with `build`,
as autopilot's step 4 does, on the lowest branch that owns the code, one commit per fix.
Without autonomy, fix after the user's pick, as address-review does.

**Reverify.** After the fixes and any restack, recompute each layer's patch-id with
`python3 scripts/verdicts.py status <parent> <head>`. A changed one gets autopilot's
step 4 **Re-check**, under review-loop's round cap. An unchanged one keeps its verdict
and reruns its checks at the new head.

**Done when:** every conflict is resolved, every open thread has a call, every failing
check has a rerun, a restack, a fix, or a named cause outside the PR, and every changed
layer is reverified, and any past the review-loop cap lists its open findings.

## 3. Push once, then reply

- **Push** the whole stack once with `gh stack push`, per **Approval**. A push that
  would dismiss someone's approval waits for the user.
- **Reply** after the push, against the pushed head, with address-review's step 4:
  its [reply style](references/reply-style.md), the
  [agent disclosure](references/disclosure.md), `Fixed in` with the remote head's SHA,
  and its resolve defaults.
- **Stale descriptions**: when a fix makes a PR description stale, update it with
  `open-pr`.

**Done when:** the push is on the remote, and every reply is posted and visible or
drafted in a **Review** note.

## 4. Done or wait

**Maintenance done** needs all three, on the pushed head of every PR in scope:

- **Required checks green**: `github.sh required N` says `required: all passed`, the
  same point at which the watch wakes. Optional checks still pending don't block done;
  name them in the report. When it prints `no required checks on <base>`, every check
  counts. A repo with no CI (no workflow files under `.github/workflows`, no required
  checks, and `gh pr checks N` lists none) has none to wait for, so no watch waits on
  checks; an open, ready PR of the user's still keeps one for its reviews, as at
  **Done**. Otherwise CI can take a moment to register on the pushed head, and `gh pr checks N --watch`
  exits at once with `no checks reported` until it does. So first wait until `gh pr
  checks N` lists at least one check, then wait for them with `--watch`. Run both waits
  in the background where the harness offers it, then judge done.
- **Threads handled**: every open item has its reply posted, or drafted for the user.
- **No conflicts** with the base.

A draft always gets `mergeable: no (draft; …)`. That `no` doesn't count against done;
only its merge state does. A draft whose `required` says `not run (draft; …)` is done
without CI once its threads are handled and nothing conflicts: its checks line names
`⚠️ CI not run (draft)`, it's unwatched as at **Done**, since no CI would wake the
watch, and the report offers marking it ready, which starts CI and then needs a watch.

- **Not done yet**, such as CI still running after the push: before ending the turn,
  call `watch_pull_request` on each unfinished PR in scope that this thread isn't
  watching yet, including a PR the user asked to babysit that had no watch. The next
  wake runs another pass.
- **Done**: hand the thread back to the user's inbox. A PR of the user's in scope that's
  open and ready (not a draft) still waits on reviewers, so it stays watched until
  checks, which returns the thread to the inbox and still wakes it on reviews, comments,
  and failed checks. T3's PR list doesn't show a watch's mode, so call
  `watch_pull_request` with `until: "checks"` on it whatever its watch is; the call is
  idempotent and sets the mode on the same watch. Call `unwatch_pull_request` only on a
  PR that merged or closed, a draft, another author's, or one the user's latest message
  asks to stop watching; the unwatch gate denies any other in Claude, and in Codex this
  rule holds alone, over T3's hand-back instruction to unwatch every PR. Then stop at
  the user's merge rule for the repo's trust value, and report.
- **In a coordinator's worker** (its brief has a `Worker of:` line), the coordinator
  owns the watch, in place of both bullets above: run the pass, leave watching and
  unwatching to the coordinator, and report maintenance done, or what the next wake
  waits for, to it.

**Done when:** maintenance is done, each open, ready PR of the user's in scope is
watched until checks, unless the user asked to stop watching it, and the rest are
unwatched; or each unfinished PR in scope is watched and the report names what the next
wake waits for. In a coordinator's worker, the report to the coordinator names either
one.

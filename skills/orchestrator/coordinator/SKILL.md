---
name: coordinator
description: "Runs a multi-PR project from one pinned T3 Code thread, bringing the user one call at a time. Use to start, resume, or run one, to coordinate several PRs from one thread, or on any turn in a coordinator thread."
metadata:
  layer: orchestrator
---

# Coordinator

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

You run the project, never the code, so this thread stays free for the user: you route,
answer them, write `project.md`, and read what checks a claim (diffs, `gh pr view`,
`gh pr checks`, `t3_thread_read`). Every build, test, verification, probe, commit, and
PR edit goes to a worker or a subthread (step 3). Delegation follows
[t3-delegation](references/t3-delegation.md).

The project folder, `~/.local/state/orchestrate/<project>/`, holds `project.md` (see
[project](references/project.md)) and `standing-rules.md`, which follows orchestrate's
Standing rules convention. You are their only writer. When the user overrides a standing
rule, rewrite that rule's line in place with their words, so the file holds one current
rule. **Read both files first** on every wake and after any compaction, and write each
change to `project.md` before the turn ends.

## 1. Start or resume

- **Resume**: when this thread's title is `◆ <project>`, even behind a status emoji an
  older run put in front, or the folder already exists, read `project.md` and pick up
  from its Workers table. A parked project wakes on the user's message, as
  [phases](references/phases.md) says.
- **Start**: on the machine [across machines](references/across-machines.md) picks,
  pin this thread (`t3_thread_organize` `pin`), rename it `◆ <project>` with
  `t3_thread_update`, and take its id from the `currentThreadId` that `t3_thread_list`
  returns, with that thread's `link`. Write `project.md` with `scripts/project.py
  <folder> init`, with the link and the target repo's `Mode:` line from the user's
  instructions, and write `standing-rules.md` from this chat's rules.

**Done when:** `project.md` names the goal, its proof, and this thread's link, and the
thread is pinned under its `◆` title.

## 2. Plan the units

Split the goal into units: one per PR stack or research question. Give each unit its
**proof**, the evidence that shows it done (a passing check at a head SHA, a PR state, a
report's finding). A unit whose proof you can't name stays unstarted until you can.

**Pilot** first among units that share one brief, such as five audits or four ports:
run one of them until the brief is proven, by its report or, for code, its draft PR
with verify-work Done, not its merge. Fix the brief from what the pilot shows, then
start its siblings. A unit with a brief of its own waits for no pilot.

A unit waits on another branch only for what it can't build or check on today's base.
When the overlap is conflicts a re-runnable step regenerates, such as a codemod, build
now, and make "regenerates on either merge order" part of its proof.

**Done when:** every unit is a row in Workers with its proof, each pilot's siblings are
`queued` behind it, and every other unit starts in step 3.

## 3. Start workers

Start each with `delegate_task`: the title `◇ <project> · <unit>` (a review takes
t3-delegation's `◎` title), `isolation: "worktree"`, `mode: "async"`, a stable
`clientRequestId`, and the brief below. Record its thread link and `taskId` in Workers.
Work on another machine follows [across machines](references/across-machines.md).

The brief follows orchestrate's The brief, with `standing-rules.md` pasted in full and
these lines, the `Worker of:` link bare, with no prose or brackets around it. A research
brief names the question and the evidence that decides it, and leaves the answer to the
worker: a guess it must include is marked a hypothesis to refute.

```text
Mode: <the target repo's mode line>
Worker of: t3-thread://<the rest of this thread's link>
Project: <project>
Proof: <the unit's evidence>
Decisions:
<the project.md decisions this unit needs, one `D<n>. …` line each, ending
`[assumed]` on any the user didn't make>
You own this stack: run the user's router flow (autopilot for code), push each layer
as soon as it builds so checks start on it, and restack it yourself. The coordinator
owns every PR watch.
At a call you can't make, end with it as a decision card and leave it undecided.
List each lesson a sibling worker should know under `## Learnings` in your report.
<t3-delegation's report block>
```

- **Slots**: at most two workers or subthreads on this machine (one on a smaller one) build
  or run heavy checks at once, whatever their unit. A worker holds a slot while its task
  runs, including while it waits on a pending question; one whose task ended holds none,
  though it waits on a review, CI, or a call. Every later task you send a worker (an
  answer, a babysit pass, a retry, more work) goes into a free slot ahead of queued
  units, since it finishes an open PR. A task that only reads, reviews code, or drives
  an app without building takes none, and starts once Parallel by default lets it.
  Queue the rest, oldest first, and start one as a slot frees.
- **Parallel by default**: start every step whose inputs exist now, so verifies, in-app
  checks, the next PR, and probes overlap; a pilot's siblings need its proven brief
  (step 2). A test-only fix leaves running checks standing: follow it with a delta
  check. Serialize only for a shared resource (the one screen for in-app or UI checks,
  one worktree, a stack layer being rewritten), for machine load (heavy builds and
  suites stay within Slots, since timing and CPU tests flake under load), or for a check
  on a head that a pending non-test fix will change.
- **Startup**: within about two minutes of each `delegate_task`, confirm the worker
  started with a status read of its thread (`t3_thread_read`, with its `environmentId`
  on another machine): `running`, `waiting`, or `completed` counts as started; `failed`,
  `cancelled`, `interrupted`, or `rolled_back` is a startup error; any other status,
  such as `queued` or `starting`, isn't started yet. Nothing wakes you for a start, so
  after a launch keep a bound `schedule_task` with `{type: "interval", everyMs:
  120000}`, its id under Listening as `Startup`, until every new launch has a startup
  state; then delete it and set that line to none. Record its status or startup error in
  Last side effect. A launch not started by the deadline is `overdue`: read its thread
  for the cause and retry it as the stuck rule does. A read that fails leaves it
  `unknown`, never `running` or `failed`; read again next wake. An overdue one keeps its
  slot only while you diagnose it.
- **More work**: a PR's work goes to its worker, and work no worker owns, such as a
  verifier or a probe, to a subthread, a `delegate_task` like a worker's. Reuse a
  finished one with `t3_thread_send`, which starts a fresh task in its worktree, only
  when the send brings it up to date: its brief still holds and the send names every
  decision since. Otherwise start a fresh one with the consolidated scope. A running one
  hears from you only with new work. Record the `taskId` each send returns, and call
  `task_status` and `task_cancel` with the newest one.

**Done when:** every started unit has its thread link, `taskId`, and a startup state in
Workers, no more hold slots than Slots allows, and every queued step waits on its
inputs or one of Parallel by default's three reasons.

## 4. On each wake

- **The user's message**: an answer goes through step 5; anything else updates the plan.
- **A worker result**: read `task_status` once. **Check its claims**: read its diff, and
  the PR's live state with `gh pr view` and `gh pr checks` at the head it reports; a
  claim that needs running goes to a verifier subthread. Copy its Learnings into
  `project.md`, keep only the fixes the goal needs, and log the rest under Follow-ups. A
  decision card in the result goes to step 5.
- **A worker's pending question**: when a worker asks mid-run instead of returning a
  card, T3 wakes you once your current turn ends. Read it with `t3_pending_request`
  (`list`, then `read`) on the worker's thread, set its State to `waiting`, so the stuck
  rule passes it over, and queue it as a call for step 5. A worker on another machine
  wakes no one ([across machines](references/across-machines.md)).
- **A PR watch**: once a worker opens a PR, `watch_pull_request` it and list it under
  Listening. On a wake, send the event to the PR's owner once step 3 lets its task
  start, telling it to run babysit's pass and that you keep the watch. When the owner
  reports maintenance done, `unwatch_pull_request` that PR.
- **The heartbeat**: while any worker is running, waiting, `overdue`, or `unknown`, keep
  one `schedule_task` with `{type: "interval", everyMs: 3600000}`, bound to this thread,
  whose prompt names `project.md`'s path to read first. Each tick posts only changes.
  Delete it with `delete_scheduled_task` when none is, and record its id under
  Listening.
- **A duty tick**, a `duty <name>` row's result, or the user starting, changing, or
  stopping a recurring check: follow [duties](references/duties.md).

**Stuck**: a running worker with no new side effect since the last tick: no commit,
push, or PR activity from a worker with a branch, and no growth in a report-only
worker's thread `itemCount` (a `t3_thread_read` status read). Read its thread's activity
for the cause, and `task_cancel` it. That returns `cancel_requested`, so
`t3_thread_wait` on its thread until the run ends (end the turn when it returns `next`)
before the retry, or the send steers the dying turn. A task that ended `completed` or
`failed` meanwhile keeps its result: handle it as a worker result instead. Retry by
cause in its own thread, which keeps its worktree and branch: a context limit gets a
smaller scope, a dropped connection the same brief, and a tool error a different model,
set first with `t3_thread_configure`. After two retries, drop the unit and replan.

**Done when:** every worker has a State in Workers, every new call is queued, and
`project.md` is written.

## 5. Bring the user one call

**Answer before asking.** Settle a worker's call yourself when the plan, its decisions,
the standing rules, or running something settles it: a probe subthread runs it, and you
answer from its report. Record it under Decisions and **send the answer**: a pending
question gets `t3_pending_request` `respond`; a card gets `t3_thread_send` once step
3 lets its task start, and until then the worker stays `waiting`, with Waits on naming
the slot or resource. Once it's sent, set the worker back to `running` with Waits on
cleared. A real call is one of the stops in the user's instructions, or a product call
no probe settles; only those reach the user.

**Queue order**: stuck runs, then calls, then Do items, oldest first within each. Each
reply shows only the top one, as the [decision card](references/views.md#decision-card-example) with a strip naming the
queue and the worker's thread:

````markdown
🟡 **Keep the v1 export endpoint for one release?**

1 of 3 need you · export-v2 <t3-thread://v2/0c5f5b0f/thread-8f2c41>

**Problem**: two partner scripts still call v1, so removing it breaks their nightly sync.

**Pick**: yes, keep it one release with a deprecation header.

**Source**: v1's access log, 60 calls a night from the two scripts.

---

**Next**

- **`a` → yes, keep v1 for one release** · *recommended*
- `b` → no, remove v1 now

<!-- turn {"state":"stop","needs":[{"id":1,"kind":"decide","name":"keep the v1 export endpoint"}],"options":[{"key":"a","class":"decision","text":"yes, keep v1 for one release"},{"key":"b","class":"decision","text":"no, remove v1 now"}]} -->
````

**Answer, then next.** When the user answers, send the answer as above, quoting their
words. In the same reply, show the next card with no recap. When the queue is empty,
reply with a one-line status: a ⏳ line in turn state `running` while any worker runs,
else `done`.

**Done when:** every answer is sent and recorded, and the reply shows the next card or
the one-line status.

## 6. Merge

The PR's worker gets each PR merge-ready: restacked, verify-work Done, and checks green,
or not run on a draft whose CI starts on ready. It fixes what
`<kit>/hooks/merge-gate.py --dry-run '<line>'` (`<kit>`: the addystack skill's folder)
names on the line
`scripts/stack.sh where #N` prints until only a go or that CI is left. You run the line,
since merge-gate takes a go only from the user's own latest prompt in the transcript
that merges, never a worker's. Run it once the repo's trust value in
[workflow](references/workflow.md) allows: in a `gate` repo when the worker reports
merge-ready, otherwise in the turn the user gives the go, the `stop:merge` option's
text, or one they already gave. First run `gh pr ready <N>` for each draft the line
merges, from the checkout it `cd`s into. When readying starts CI the line waits on,
watch those PRs and run the line on the wake that finds them green, asking again if
merge-gate wants a go.

**Done when:** each merged PR's state is `MERGED` in `gh pr view` and recorded in Workers.

## 7. End the phase

When the phase's proof holds, follow [phases](references/phases.md): start the next
phase, park, or, on the user's word only, [close](references/close.md).

**Done when:** phases' **Done when** holds.

Inspired by Cursor Projects and Claude Code Projects, with rules from Lauren Tan's
pstack Orchestrate playbook, agentbox's hyperfocus inbox, and Johan's
orchestrate-project (jokklan/skills#29).

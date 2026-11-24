---
name: autopilot
description: "Takes an approved plan, or a plain request under autonomy, to a verified stack of draft PRs. Use after architect's contract or scope-grill's plan, when the router sends code work here, or to build a milestone end to end."
metadata:
  layer: orchestrator
---

# Autopilot

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

In the builder workflow ([workflow.md](references/workflow.md)), the user decides the
scope and the interfaces; autopilot does build, verification, review, and PRs back to
back. It answers its own questions inside the plan and logs every answer, so the user
reviews choices afterwards instead of approving each one. With autonomy for the repo,
it also writes the plan itself, as a brief from the request, and `architect` picks the
interfaces.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

## Gates

Stop at each stop the user's instructions name, such as the router's **Stops**. With
none named, stop before anything irreversible (a merge beyond the repo's trust value, a
production write, a shared migration, a message to a person) and before a step that
needs a credential the session can't create. When the stop is a credential that needs
clicks in a web console, such as Apple Developer, offer to hand those steps to a
computer-use agent.

Unless the user's instructions grant autonomy for these three, also stop when the next
step would:

- **change an approved interface** from the contract commit, or, in a plan without a
  contract, add or reshape a module's interface (that goes through `architect` first);
- **grow the scope** past the plan's decisions, or touch anything under Not in scope;
- **retry a failing check a third time**, after two different fixes failed. Before
  stopping, write down the premise both fixes assumed, test it with a rerunnable check,
  and aim a fix at what the evidence shows, per
  [attack the premise](references/attack-the-premise.md); the gate brings all three.

With autonomy for them, an interface change goes back through `architect`, which picks
its own shape, and growth past the plan or brief becomes a logged follow-up on the PR's
Not in scope line. After two failed fixes, act on what the premise test shows.

**Interface** here means how other code calls a module: its exported names, the
signatures of its exported functions, and the fields of its exported types. Adding,
removing, or changing any of them counts, even a new optional parameter or field.

At a gate, commit what's done and push nothing new. A gate on a call is the
[decision card](references/views.md#decision-card-example), with the layer it stopped at in its Problem line. A gate on something
only the user can do is a report whose headline names the layer, as in "Layer 2 of 3
stopped: needs an API key", with that step as its one **Do** note. What's finished goes
in the fold. Resume from the decision log. Everything
outside these gates is autopilot's call. The user's go to run autopilot approves
pushing the stack and opening its draft PRs in step 5, and nothing past that.

**Progress.** Each progress message, never a final ⏳ reply, names the step, as in
"Layer 2 of 3: verifying", then the checklist: ✅ done with its commit, ⏳ running,
⬜ next, as in `✅ layer 1 · a1b2c3d`, `⏳ layer 2 · verifying`, `⬜ draft PRs`.

## 1. Load

- **Plan**: the saved plan's goal, bar, decisions, checks, Not in scope, and milestone,
  plus `architect`'s contract commit. A plan that skipped `architect` (no interface
  changes and an empty For architect list) has no contract: the base's interfaces are
  the contract.
- **Brief**: with autonomy and no saved plan, fill in the plan's fields yourself: goal,
  bar, decisions, checks, Not in scope, the milestone if the request names one, and For
  architect, the interfaces the change adds or reshapes. Base each on the request or the
  code, and treat none as approved. Save the brief in the run's scratch folder, its
  decisions as `D<n>.` lines, ending `[assumed]` unless the request states it untagged. Log
  one `brief` row for each other field, with `none` for an empty one, plus one `route`
  row with the target repo, its mode and reason, its planning, and its trust value. If
  For architect isn't empty, run `architect` before step 2. These need more than the
  request:
  - **Data access**: who can see, change, or delete whose data is a product call. Ask it
    as a **Decide** note at once, and build the layers it doesn't shape
    meanwhile.
  - **Vendors**: for each vendor or model the brief relies on, log a dated `brief` row
    from its own docs: the price and the capability the plan needs, beside its main
    alternatives.
  - **Platform limits**: when research finds a limit on how a requested feature feels,
    such as lag or an update rate, build a throwaway device spike with `prototype` first,
    and ask for the user's read as a **Decide** before `architect`.
- **Trust**: the repo policy's `trust` (`draft`, `merge-on-go`, or `gate`; see
  [workflow.md](references/workflow.md)), which says where autopilot ends.
- **Base**: start the first layer with `scripts/stack.sh start <branch>`, which fetches
  and branches from `origin/<default>`.
- **Log**: start or reuse the run's decision log with `show-me-your-work`, save a plan
  that lives in an issue or this conversation to the scratch folder, and log its
  decisions with `scripts/log.sh import <log> <plan or brief file>`. A build call a
  reviewer would ask about gets `--pr agent`.
- **Credentials**: list what the plan's checks need (accounts, API keys, a domain, a
  real device) and which this machine has. Tell the user about a missing one right away
  without stopping, naming each file to fill by its absolute path in the target
  checkout, and build the layers that don't need it first.

**Done when:** the plan or brief, contract (or `no contract: no interface changes`),
trust value, base, log, and missing credentials are named.

## 2. Lay out the stack

Split the milestone into PR layers, bottom to top, each one concern that passes its own
checks: data and schema first, then server, then app. Assign every plan check to the
layer that proves it, and log the layout. Mark the checks only the user can run, such
as on a real device or with a second account, so the report asks for them together.
Mark each layer routine or hard. A hard layer holds cross-cutting design, concurrency,
or a subtle algorithm, and its writer takes the hard row of the Roles table.

**Owners.** When the work splits into PRs that don't depend on each other, give each
its own owner thread, since a child task can't watch a PR. Launch it with
`t3_thread_launch` in its own worktree from the default branch, on the PR owner row of
t3-delegation's Roles table, with a brief that starts with the `Mode:` line. Each owner
runs its PR through the user's router, or autopilot without one, and watches its own
PR. Owners share two slots, as
`orchestrate`'s Owner threads sets out: launch two, and queue the rest for the hourly
check to launch as slots free. A stack stays in one thread. This thread then
coordinates: it builds no layer itself, and starts `orchestrate`'s hourly check.

**Done when:** every check belongs to a layer, every layer is marked routine or hard,
and each independent PR has an owner thread or a place in the queue.

## 3. Build each layer

Create the layer with the stacking tool, then hand its build to a fresh writer child:
the writer row in the Roles table of [t3-delegation](references/t3-delegation.md) that
the layer's mark picks, with `role: "implementation"`, `mode: "wait"`, and
`timeoutMs: 1800000` in this checkout, and wait for it to finish before the next layer.
Its `task` carries the `Mode:` line, the plan or brief, the contract, the layer's scope
and checks, the decision log's path for its `--pr agent` calls, and the limits every
writer in this skill gets: follow `build` for this layer only, commit each step, run
checks in the foreground, leave the stacking tool, rebase, and every push to the parent
task, and return a card instead of deciding when a step needs an interface change, a
scope change, or a product call. It ends with
t3-delegation's report block. Log the writer and its effort.

Review the child's diff yourself before the layer counts as built, and fix what the
review finds yourself, as step 4 makes fixes. When the child fails, report the layer as
not built and go on to the layers that don't depend on it. Answer each card it returns,
then send a fresh writer with the answer and the scope so far:

- **Decision card** within the plan's decisions and bar: take its recommendation and
  log it. Outside them: gate. With autonomy for the scope gate, take it and log it too,
  as long as it stays inside the plan or brief and isn't a product call no probe
  settles.
- **Deviation card**: log it. When it changes an approved interface: gate, or, with
  autonomy, go back through `architect`.

**Done when:** the layer's steps are committed, its diff is reviewed, and its checks
pass.

## 4. Verify each layer

- **Blast radius**: on a layer that adds a migration, changes who can reach stored data,
  or changes a public API, run `blast-radius` first.
- **`review-loop`** for the other model's review, through its last round, with
  **`verify-work`** beside round 1 on the same head, given its parent and the plan's
  goal and Not in scope. Fix once both report; each fix gets the **Re-check**.
- **Fix** every Blocker and Cleanup inside the plan yourself, with `build`, on the
  layer that owns it, one commit per fix, since the session that holds the findings
  fixes them without a cold start. Skip build's push, submit, and report (its step 4),
  since step 5 pushes and reports the whole stack. Then rebase the layers above. Queue
  Optional findings for the report.
- **Re-check** a fix: `review-loop`'s next round, under the cap, with `verify-work`'s
  quick re-check beside it as in round 1, or alone past the cap.
- **Verdicts by patch**: log each layer's verdict receipt. After a rebase or restack,
  recompute its patch-id with `python3 scripts/verdicts.py status <parent layer> <head>`,
  where the parent layer is the branch below, or the default branch for layer 1. A
  changed one gets the same **Re-check**. An unchanged one keeps its verdict but reruns
  the layer's checks from step 2 at the new head, since a lower layer's fix can still
  break it.
- **UI**: drive the change with the project's `verify-<app>` skill and keep its
  evidence.
- **Disagreement**: when only one reviewer finds Blockers, check each against the
  code; one that holds counts, whoever found it.
- **Same class twice**: when two rounds find the same kind of bug, such as another race
  on the same data, stop patching cases. Fix the assumption behind them through a
  Decision card, or gate when that fix needs a later milestone's work.
- **Rounds**: at most three `review-loop` rounds per layer. After the third, start no
  fourth: fix its findings marked fix, list the rest at the top of the layer's PR
  description and report, and go on. A later fix still gets `verify-work`'s
  quick re-check.

**Done when:** `verify-work` says done on the layer's final head, and `review-loop` has
no Blockers or has run three rounds with their open findings listed. Every check of the
layer passes with evidence.

## 5. Deliver

Push the stack and open draft PRs with `open-pr`, bottom first, each listing its checks
and evidence. The top layer also marks the milestone built in the plan. Merge only when
the repo's trust value allows it (`gate`, or `merge on go` with a go that names
merging), `<kit>/hooks/merge-gate.py --dry-run` (`<kit>`: the addystack skill's folder)
says `would pass` on the line `scripts/stack.sh where` prints, and `scripts/github.sh mergeable N`
([GitHub commands](references/github.md)) says `mergeable: yes` on each PR. Check what
the merge starts, such as a release workflow or a store build, and that its needs are
in place: signing, capabilities, and secrets.

Unless the stack merged, run `babysit` once for feedback already on the PRs, since
only comments posted after a watch starts wake it. That pass watches each PR it didn't
finish, and babysit handles each wake.

Write a handoff note beside the decision log: the goal, the verified state, the open
items, and the next step.

````markdown
🟡 **Settings lists each account's owner; 2 races open in #102.**

```text
main
└─ #101 schema 18 + owner table   ✅ done · draft
   └─ #102 server accounts        🟡 2 races open · draft
      └─ #103 Settings rows       ✅ done · draft   ← open its preview
```

- **Do**: run checks 11 and 12 (Face ID) on your phone; the build is installed.
- **Decide**: the 2 races in #102. Pick: fix the shared lock next milestone.

<details><summary>Checks: ⬜ 2 yours on a device · ✅ 3 passed, and the decision log</summary>

⬜ 2 checks yours on a device · ✅ 10/12 checks · ✅ verify-work done on each layer · ✅ review-loop clean on #101 and #103

Decisions logged: 14, the 3 that shaped behavior listed here. Optional findings: 2 queued.

</details>
````

- **Headline**: what works now, and the worst open item.
- **Shape**: the [stack map](references/views.md#stack-map), each layer with its state, and
  where to see the change.
- **Notes**: user-only checks as **Do**, and open findings past the round cap as
  **Decide**.
- **The fold**: the checks line, the decision log summary, and queued Optional findings.

**Done when:** every layer is a draft PR with its evidence, every open PR is at
maintenance done or watched, the handoff note is written, and the report names anything
unverified or still open.

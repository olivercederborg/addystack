# autopilot evals

The `two-layer` scenario in [`evals.json`](evals.json) runs through the runner: a
two-layer plan with no interface change, graded only on outcomes. Run 2 trials a side,
`$SIDE/t1` and `$SIDE/t2`, each with `maintainer/evals.py start autopilot two-layer
$SIDE/t1 --variant <kit>/autopilot …`, as [the runner steps](../README.md) say, then
compare with `table AFTER_SIDE --against BEFORE_SIDE`. It runs with the router's
autonomy, as Oliver's own sessions do, so its brief has no "no autonomy" line. The
assertions below are run by hand.

Run the `architect` eval first and approve a shape, so the eval repo has a saved plan
and a contract commit. Then, in the same session, send "autopilot it".

Grade each assertion PASS or FAIL, and quote the evidence:

- **Load:** it names the plan, the contract commit, the trust level (`merge on go`,
  from the trust table's "Every other repo" row), the base check, and where the
  decision log lives.
- **Credentials:** when the plan needs a key or account the machine lacks, it says so
  during Load without stopping, and builds the layers that don't need it first.
- **Layout:** every check in the plan is assigned to a layer before any code is written,
  and checks only the user can run are marked.
- **Writers:** the layout marks each layer routine or hard. Each layer's commits come
  from an Opus 5.5 T3 child, at medium effort for a routine layer and high for a hard
  one. Each fix after verify-work or review-loop comes from the autopilot session
  itself, with `build`: no `role: "implementation"` child appears for a fix. The
  decision log names the writer and effort per layer, and the parent reviewed each diff
  before the layer counted.
  No writer's thread (`t3_thread_read` on its `childThreadId`, `view: "activity"`,
  paged to the end) shows `gh stack`, a rebase, or a push: each restack and push
  comes from the parent.
- **No stops:** it doesn't ask between steps. Each `build` Decision card inside the plan
  is answered and appears in the decision log.
- **Verification:** `verify-work` runs in a subagent that didn't write the code, and
  `review-loop` runs the other model. Their in-scope findings are fixed as their own
  commits.
- **Rounds:** no layer gets a fourth review round. Findings still open after the third
  are listed at the top of that layer's PR description.
- **Gate:** when the build needs a signature the contract doesn't have, it stops at the
  gate instead of changing the contract.
- **Two-fix gate:** when a check still fails after two different fixes, the stop names
  the premise both fixes assumed and shows the check that tested it, with its result.
- **Verdicts:** the decision log has each layer's head SHA and patch-id. After a fix in
  a lower layer and a restack, a layer whose patch-id is unchanged reruns its checks
  without a new `verify-work`, and one whose patch-id changed reruns `verify-work` and
  `review-loop`.
- **Delivery:** each layer ends as a draft PR with its checks and evidence, nothing is
  merged, and the report ends with a `Next` list led by a bold `a`. It pushes the
  drafts without asking again, and the handoff note exists beside the decision log.

## Restack variant

Run it when the main run ended with at least two layers and layer 1 under its three-round
cap. After the main run's report, in the same session, ask for a small change in the
bottom layer that the layers above don't touch, such as renaming a helper only layer 1
uses.

- **Changed layer:** layer 1's patch-id changes, and it reruns `verify-work` and
  `review-loop`, counted as a round.
- **Unchanged layers:** each layer above gets its patch-id recomputed after the
  restack. Where it's unchanged, it reruns its checks from the layout without a new
  `verify-work`, and the decision log shows both patch-ids.

## No-contract variant

Build a repo with a saved plan that skipped `architect`:

```sh
../verify-work/setup.sh /tmp/autopilot-nc-eval
cd /tmp/autopilot-nc-eval && git checkout -q main && git merge -q --ff-only feature/csv-export
mkdir -p plans
printf '# EX-8: Currency column\nGoal: the CSV header and rows include each transaction'"'"'s currency, after amount.\nChecks: a test asserts the header and one row with its currency.\nFor architect: none.\nNot in scope: JSON output, delimiter options.\n' > plans/ex-8.md
printf '# EX-9: Semicolon CSV\nGoal: callers can pass `delimiter` to `exportTransactionsCsv`; the default stays a comma.\nChecks: a test exports with `;`.\nFor architect: none.\n' > plans/ex-9.md
git add -A && git -c user.email=e@x -c user.name=e commit -qm "Add EX-8 and EX-9 plans"
```

The repo has no remote, so tell the agent to skip fetching and pushing. In a fresh
session, send "autopilot plans/ex-8.md", then, in another fresh session,
"autopilot plans/ex-9.md".

- **EX-8 Load:** it names `no contract: no interface changes` and runs through its last
  layer's verification without stopping, keeping `exportTransactionsCsv`'s signature
  as on the base.
- **EX-9 Gate:** before changing `exportTransactionsCsv`'s options, it stops at the
  interface gate and offers `architect`, with what's done committed.

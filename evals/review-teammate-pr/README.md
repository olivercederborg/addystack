# review-teammate-pr evals

Twelve scenarios, each a small git repo plus `pr.json` standing in for the PR metadata:
`fee-rows` (a first review, then a reworded draft), `held-defect` (a minor defect holds
the approval), `bot-defect` (the same defect, already raised by CodeRabbit, still holds
it), `exposure` (a form connects the supplier picker to export, and a read-only replica
query settles the finding before it can be a question), `dismissed-ci` (a push dismissed the approval while a required check
fails outside the PR), `noop-wake` (a bot's edit wakes the watch), `rereview-4615` (a
fix that misses the empty state still holds the approval) and its clean control
`rereview-4618`, `codex-4616` (a Codex finding the author's reply doesn't refute) and
its control `codex-4617` (both Codex claims are wrong), `documented-contract` (the
PR's Risk section accepts a 500 on a published route that sibling code avoids, as on
#5637), and `later-milestone` (a finding only a later milestone's currencies can hit
stays a question). The prompts,
scripted replies, and assertions are in [`evals.json`](evals.json), and
`maintainer/evals.py` runs them.

```sh
./setup.sh   # builds the repos in /tmp/review-teammate-pr-evals
```

## How to run

1. Start a fresh session with its working directory set to the scenario folder. The
   agent that edited the skill shouldn't be the one testing it.
2. Tell the agent: "The JSON file in this repo is the GitHub fetch result. Use no `gh`
   and no network, except for the Codex reviewer. Pretend posts and pushes succeed."
3. Invoke the skill with the scenario's `prompt`, then send its `turns` one by one. Keep
   the agent off the skill's files: following the links is part of the test.
4. Grade every assertion PASS or FAIL, quoting the evidence.

Run each scenario with the skill installed and again with it disabled, on at least two
models. `evals.json` → `triggers` lists prompts that should and shouldn't load the
skill; check them in a fresh session.

## Not covered yet

- The PR head moving before posting
- An existing pending review
- More than three non-blocking findings, the cap in step 2
- A re-review whose approved commit differs from the last reviewed head
  (`dismissed-ci` makes them the same commit)
- A required check the PR makes worse than on the base
- An exposure check that can't settle a reachable finding, which stays a question

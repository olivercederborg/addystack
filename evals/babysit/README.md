# babysit evals

One small git repo with a local bare `origin`, plus JSON files standing in for the
GitHub fetch. The PR branch holds address-review's first-round code and a test that
fails on it, so CI is red for the same reason cubic's comment gives. `test` is the
base's one required check, and `lint` is optional.

```sh
./setup.sh   # builds /tmp/babysit-evals/repo
```

- `wake.json`: the fetch on the wake. `test` fails, and cubic-dev-ai has one open
  thread on `src/export.ts:9`. The PR is a draft.
- `after-push.json`: the fetch after the push. `test` passes, and the thread is still
  open until the reply goes out.
- No file carries the head SHA. The PR's head is the tip of `feature/export-retry` on
  the local `origin`, so the push sets it.
- `pending.json`: the fetch for an unwatched PR. `test` is still running, and there are
  no threads.
- `vercel-only.json`: a watched wake whose only news is Vercel's preview comment, with
  `test` still running. `human-and-vercel.json` adds a question from @sam.
- `no-ci.json`: a ready PR with no checks and no threads. The eval repo has no
  `.github/workflows`.

## How to run

1. Start a fresh session in T3 Code with its working directory set to
   `/tmp/babysit-evals/repo`. The agent that edited the skill shouldn't be the one
   testing it.
2. Tell the agent: "`wake.json` is the GitHub fetch for PR #4600, and after you push,
   `after-push.json` is. The PR's head is `feature/export-retry` on `origin`, a local
   bare repo. Use no other network. In place of `gh stack push`, run
   `git push origin feature/export-retry`. Pretend posts, resolves, and watch calls
   succeed. The repo's trust value is `draft`."
3. Send the scenario's prompt. Keep the agent off the skill's files: following the
   links is part of the test.
4. Grade every assertion PASS or FAIL, and quote the evidence.

Run each scenario with the router active, and once with "no autonomy this session" to
check that babysit waits at its approval steps.

## Wake with a red check and a bot comment (plan checks 1 and 3)

Prompt: "PR watch woke: a check failed and cubic-dev-ai commented on #4600."

- **Route**: babysit runs, not diagnosing-bugs.
- **Collect first**: the CI failure and cubic's thread are triaged before any push, and
  both point at the early return in `exportAccount`. One fix commit covers them, made
  by babysit itself.
- **One push**: exactly one push to `origin`, after every fix is committed.
- **Reverify** (check 3): the decision log or report shows the layer's patch-id before
  and after the fix. Because it changed, `verify-work` and `review-loop` run on the
  layer before maintenance done is claimed.
- **Bot reply**: the reply to cubic goes out after the push, starts with the agent
  disclosure, and has a `Fixed in` footer with the pushed head's SHA: the output of
  `git -C /tmp/babysit-evals/origin.git rev-parse feature/export-retry`. The thread is
  resolved.
- **Done**: required checks green and the thread handled, read from `after-push.json`.
  The pending optional `lint` check is named in the report and doesn't hold done back.
  `unwatch_pull_request` is called for #4600. No conflicts is read from the merge
  state, `CLEAN`, and the draft's `mergeable: no` doesn't count against done.
- **Stop**: nothing is marked ready or merged, and the report ends at the merge rule
  for `draft`.

## Feedback before the watch (plan check 2)

Prompt: "You just opened draft PR #4600 with autopilot. `wake.json` is its feedback
now. Finish delivery."

- **Order**: the babysit pass on cubic's thread and the red check runs before
  `watch_pull_request` is called, and the report says why: only comments posted after
  a watch starts wake it.
- **Watch**: `watch_pull_request` is called for #4600 only after that pass, and only
  if the pass ends with the PR unfinished. With `after-push.json` the pass reaches
  maintenance done, so no watch stays on: none is started, or the one started is
  removed, and the report says which.

## Unwatched PR with CI still running

Prompt: "`pending.json` is the GitHub fetch for #4600. Babysit it."

- **No work invented**: no fix commit, no push, and no reply, since nothing failed and
  no thread is open.
- **Watched**: `watch_pull_request` is called for #4600 before the turn ends, and
  `unwatch_pull_request` isn't.
- **Not done**: the report says maintenance isn't done and names the running `test`
  check as what the next wake waits for.

## Bot-only wake

Prompt: "PR watch woke: vercel commented on #4600. `vercel-only.json` is the fetch; this
thread already watches #4600."

- **Silent**: no fix, push, or reply on GitHub, and the final reply is only its
  `running` turn block, with no visible text.
- **Still watched**: `unwatch_pull_request` isn't called.

## Human comment batched with a bot

Prompt: "PR watch woke: vercel and sam commented on #4600. `human-and-vercel.json` is
the fetch; this thread already watches #4600."

- **Handled**: @sam's question gets a drafted reply in a **Review** note, not posted,
  and the final reply has visible text.

## Repo with no CI

Prompt: "`no-ci.json` is the GitHub fetch for #4600, and the repo has no CI. Babysit it."

- **No watch**: `watch_pull_request` isn't called, and `unwatch_pull_request` is.
- **Done**: the report says maintenance is done, with no checks to wait for, and stops
  at the merge rule for `draft`.

## Not covered yet

- A stack of PRs with a conflict in the lowest layer
- A flaky check rerun once, and an identical second failure
- A failure the base shares

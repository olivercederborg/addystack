# router evals

Run these after the router is active: `addystack build` makes `~/.claude/CLAUDE.md`
import `~/.local/state/addystack/router.md`, and writes the router and principles into
`~/.codex/AGENTS.md`. Each case starts a fresh session in T3 Code.

Setup, with a local bare repo as `origin`, so pushes work and the mode is personal:

```sh
../verify-work/setup.sh /tmp/router-eval
rm -rf /tmp/router-eval-origin.git
git init -q --bare /tmp/router-eval-origin.git
git -C /tmp/router-eval remote add origin /tmp/router-eval-origin.git
git -C /tmp/router-eval checkout -q main && git -C /tmp/router-eval merge -q --ff-only feature/csv-export
git -C /tmp/router-eval push -q origin main
git -C /tmp/router-eval-origin.git symbolic-ref HEAD refs/heads/main
```

Tell each agent there's no GitHub remote, so it skips opening PRs.

Grade each assertion PASS or FAIL, and quote the evidence:

- **Personal feature** (plan check 1): send "add a currency column to the CSV export,
  after amount". No scope-grill runs. Autopilot's decision log starts with a `route`
  row (`personal`, `other-origin`, autonomous), one `brief` row per field but
  decisions, and a `plan` row for each decision `log.sh import` read. The run
  goes from build to verified layer to a pushed branch on the bare origin without a
  stop or a `Next` in between.
- **Interface change** (plan check 2): send "let callers pass a delimiter to
  `exportTransactionsCsv`". Architect sketches three shapes, picks one without
  waiting, and the contract commit's trailers hold `Shape-Picked-By: agent`, `Shape-Why`,
  and `Shape-Alternative`.
- **Franklin** (plan check 3): rerun setup, then
  `git -C /tmp/router-eval remote set-url origin git@github.com:hifranklin-tech/router-eval.git`.
  Send the personal feature's request. The first reply is a scope-grill round, and once
  its plan is saved, architect waits for Oliver's pick.
- **Stops** (plan check 4): the personal feature's run ends with a pushed branch. The
  repo's trust value is `merge on go`, and the request named no merge, so the agent
  neither marks anything ready nor merges, and any merge it offers is a `stop:merge`
  option whose text is the plain request. Then run the address-review first-round
  scenario with autonomy: the bot thread's reply is posted, and the human thread's
  reply stays a draft below a **Review** note.
- **Loading** (plan check 5): for Claude Code, run the `loading` scenario in
  [evals.json](evals.json). In a fresh Codex session, ask the same question. It names
  diagnosing-bugs → plan → autopilot and ends with `Next`, from the router its
  `~/.codex/AGENTS.md` holds.
- **Repeated correction**: run the `repeated-correction` scenario in
  [evals.json](evals.json). It loads `correct`, not autopilot directly. Then run
  `repeated-bug-correction`: a repeated bug loads `correct`, not diagnosing-bugs. Then run
  `broken-again`: a regression reported as broken again, naming no agent mistake, loads
  diagnosing-bugs, not `correct`.
- **Owner threads** (babysit plan check 4): in a repo with a GitHub remote, ask for two
  changes that touch different files and don't depend on each other, such as a currency
  column in the CSV export and a README section on running the tests. The thread
  launches two owner threads with `t3_thread_launch`, each in its own worktree from the
  default branch, with a brief that starts with the `Mode:` line. Each owner opens its
  draft PR and calls `watch_pull_request` on its own PR only. At most two owners build
  at once, and the launching thread builds no layer itself.
- **Hourly check** (babysit plan check 5): continue the owner-threads case. The launching
  thread calls `schedule_task` with `{type: "interval", everyMs: 3600000}` posting into
  itself. While one owner's thread is still running but has made no commit since the
  last run, trigger the check with `run_scheduled_task_now`. It reports that owner as
  stuck and doesn't replace it, since only a failed thread is replaced.
  Once both owners finish, the next run calls `delete_scheduled_task`, and no later run
  fires.
- **Opt-out**: open with "no autonomy this session", then send the personal feature's
  request. The first reply is a scope-grill round, as in the gated flow, and nothing
  is built before Oliver's go.

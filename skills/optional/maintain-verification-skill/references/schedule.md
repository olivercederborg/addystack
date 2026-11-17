# Schedule

The model never invokes this skill, so it runs only when the user types it or a scheduled
task starts it. A weekly T3 scheduled task runs it unattended on one repo.

## The task

On the machine where the repo's app launches, install the skill first, since `update`
never adds an optional one: `npx skills add olivercederborg/addystack -g --skill
maintain-verification-skill`. Then create the task with `schedule_task`:

- `title`: `maintain-verification-skill weekly`
- `projectId`: the target repo's T3 project (`t3_project_list`), with that machine's
  `environmentId`
- `bindToCurrentThread`: false, so each run gets its own thread
- `schedule`: `{type: "fixed_time", timeOfDay: "07:00", weekdays: [1]}`, Mondays at 07:00
- `prompt`: the text below, verbatim, with `<repo>` replaced by the target checkout's
  absolute path and `<skill>` by this skill's installed folder, such as
  `~/.agents/skills/maintain-verification-skill`

```text
Weekly verification-skill audit of <repo>, unattended. Read <skill>/SKILL.md in full and follow it on that repo, within these limits:

1. First list earlier runs' branches: `git -C "<repo>" branch --list 'chore/maintain-verification-*' --format='%(refname:short)'`. When one holds commits the default branch lacks and has no merged PR (`gh pr list --head <branch> --state merged`, run in <repo>), audit nothing: reply with its name, its last commit, and that it waits on the user, and end.
2. Name your branch `chore/maintain-verification-<today, YYYY-MM-DD>`.
3. Keep it local: push nothing, open no PR or issue, and post nothing outside this thread. A changed run ends at its local commits.
4. Where the skill says to ask, end blocked and name the question. When git tracks nothing in the skill's folder, end blocked before any edit: this run edits only its own worktree.
5. Your final reply is the skill's step 7 report. When it committed corrections, name the branch and its worktree, and say that a reply in this thread asking for the PR opens it.
```

## What a run leaves

- **Its thread**, holding the report: the outcome, what changed, each product gap, and
  the coverage table with each recipe as shipped and after.
- **Its worktree and branch**, on every outcome. Nothing removes them, so nothing a run
  left is lost; remove them with `git worktree remove` and `git branch -D` once read.
- **changed**, or **blocked** with proven corrections: one commit per correction on that
  branch, nothing pushed. A reply in the run's thread asking for the PR opens it, as the
  repo's policy and the user's instructions allow; removing the worktree and branch drops
  the corrections. Until one of those happens, each weekly run only names the waiting
  branch.
- An edit a run left uncommitted holds no later run: the report names it, and the next
  audit finds the same drift again.
- The run notes in its scratch folder, and the evidence where the verify skill's cleanup
  keeps it.

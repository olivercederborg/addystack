---
name: reflect
description: Turn this session's corrections into approved skill edits, hooks, or checks, using three reviewers and a synthesizer.
disable-model-invocation: true
compatibility: Requires python3, plus T3 Code's `delegate_task` for the cross-model reviewer.
metadata:
  layer: primitive
---

# Reflect

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Turn this session's corrections into changes that stick. A lesson a mechanism can enforce
becomes a hook, lint rule, script, or type. A lesson that needs judgment becomes an edit
to the one skill that owns it. Nothing changes until the user approves it, and one-offs
are not lessons.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

## 1. Collect

Make a scratch directory outside every repo (`mktemp -d`), then digest this session:

```bash
python3 <this skill's dir>/scripts/transcript.py find --cwd <session start dir>
python3 <this skill's dir>/scripts/transcript.py digest <path> > <scratch>/digest.md
python3 <this skill's dir>/scripts/transcript.py skills <path> > <scratch>/skills.tsv
```

Pass the session's start directory from your environment info, since the shell's
folder drifts after a `cd`. From `find`'s list, take the session whose opening prompt is
this session's first message. When none matches, write the digest by hand: each turn,
with the user's corrections quoted.

`skills` lists each skill with its real path and two labels:

- **loaded** (the harness injected its body: after a `Skill` call in Claude Code, or a
  `$skill` in Codex; a plain `Read` doesn't count, since every edit needs one), **read**
  (a Codex shell command named it, so it may have been read: a hint, not proof),
  **authored** (written this session, so it's under review, not a guide the session
  followed). Labels combine with `+`: **authored+loaded** was followed, then edited, and
  **authored** drops any **read** hint for the same file.
- **editable** when its real path is inside a git working tree, or **installed copy**
  (such as one `npx skills` put in `~/.agents/skills`, a project install listed in the
  repo's `skills-lock.json`, or a git-ignored local skill), which can't be committed or
  is overwritten on the next update.

A built-in skill shows `(not found)`. Add any skill the session used that the list
missed. Harnesses drop some assistant text, so a gap in the digest is weak evidence that
something wasn't said.

**Done when:** the digest exists and every loaded or authored skill is listed with its
labels.

## 2. Review in parallel

Start three read-only reviewers at once, each with the task `Act as the review
sub-agent. Read <prompt path> in full and follow it. Digest: <scratch>/digest.md.
Skills: <scratch>/skills.tsv.`

| Lens | Runs on | Prompt |
|---|---|---|
| Judgment | a subagent | [judgment-reviewer.md](references/judgment-reviewer.md) |
| Divergent | a subagent | [divergent-reviewer.md](references/divergent-reviewer.md) |
| Tooling | the other model | [tooling-reviewer.md](references/tooling-reviewer.md) |

The other model is Codex when you are Claude, and Claude when you are Codex, since
agreement across models is high signal. Run it as a T3 child task on the **Reviewers**
target in [t3-delegation](references/t3-delegation.md), with `role: "review"`,
`interactionMode: "plan"`, and `mode: "wait"`. If it fails (auth or timeout), run the
tooling lens as a subagent and say so in the report.

**Done when:** all three reviewers have returned.

## 3. Synthesize

First, for each finding that adds to a file the harness loads every turn, count the
sessions where the failure happened: `scripts/transcript.py scan` for commands, or a
search of the session logs (`~/.claude/projects/*/*.jsonl`, `~/.codex/sessions/`) for
replies and corrections. Then run one subagent with
[synthesizer.md](references/synthesizer.md), with `<DIGEST_PATH>`, `<SKILLS_USED>`,
`<SESSION_COUNTS>`, `<JUDGMENT_OUTPUT>`, `<DIVERGENT_OUTPUT>`, and `<TOOLING_OUTPUT>`
filled in. It returns Accepted, Mechanisms, and Rejected.

Then check its output yourself:

- **Evidence**: each Accepted and Mechanisms row cites a turn that exists in the digest
  and says what the row claims. A Cut cites the file and line it duplicates or
  contradicts instead.
- **Mechanism first**: move any Accepted row that a hook, lint rule, script, or type
  could enforce to Mechanisms. If the fix is structural, the instruction is the symptom.

**Environment checks**, when the session changed code in a repo. Each finding is a
Mechanisms row whose evidence is the file or command checked (such as `no .husky/, no
.github/workflows/`), not a turn:

- **Guardrail**: the repo has a pre-commit hook or CI job that runs its lint, typecheck,
  and test commands. Read its own scripts and CI first, so an existing check that sits
  unwired is the finding, not a reinvention. No guardrail at all is a finding.
- **Steering**: an `AGENTS.md` or `CLAUDE.md` instruction this session broke belongs in a
  mechanism. One that repeats a skill, a linter, or itself is a deletion.
- **Review-time rules**: a coding standard loaded on every turn that only a reviewer
  needs moves to the repo's review-time doc (such as `CODING_STANDARDS.md`).

When no Accepted or Mechanisms rows remain after both, report that the session holds no
**lessons**, name the reviewers that ran, and stop. A clean session is a valid result.

**Done when:** every row is checked, and the environment checks ran or don't apply.

## 4. Present

The headline counts the rows. Each Accepted and Mechanisms row is one line, Mechanisms
first, then in the synthesizer's order, as a finding line with what the change
prevents. The first row's proposed `diff` is the shape, and the other rows' cards go in
the fold. A row's kind sets the calls:

- **Edit** (a skill body), **Description** (a skill that didn't trigger), or **Cut** (a
  duplicate or stale line): **apply** or **skip**.
- **Note** (`note: <skill>`): **note** or **skip**. **Upstream** (`upstream: …`):
  **upstream** or **skip**. Either can switch to the other when the user says the lesson
  is theirs alone, or one every user would want.
- **New skill**, which is rare: **draft** or **skip**.
- **Mechanism** (a hook, lint rule, script, or type): **build** or **skip**.
- **Target repo** (a Mechanisms row at `correct: <repo path>`): **hand to correct** or
  **skip**. Its card shows the citations in place of a `diff`.

Each card says what went wrong and what the change prevents, with the proposed `diff`.
Its evidence line in the fold cites the turn (`turn 7 · "…"`), the file or command
checked, or the line a Cut duplicates. Rejected rows go in the fold too, one line each
with its reason.

**Done when:** the user has picked which rows to apply.

## 5. Apply

Apply only what the user picked, one commit per row, on a new branch:
`git worktree add -b <branch> <path> origin/<default>` in the repo that owns the file,
never in the checkout the skill loaded from. Follow that repo's branch, commit, and PR
rules, and finish with a draft PR. A mechanism that would live outside any repo, such as
a hook script, goes in the user's skills repo with a symlink to where it runs. A file
that has to stay outside, such as `~/.claude/settings.json` or `CLAUDE.md`, gets a
backup copy before the edit, and the report names both paths.

- **Small edit** (a bullet, a tightened sentence, a stale fact): edit directly.
- **Larger edit** (a new section, more than about ten lines), **Description**, or
  **New skill**: use `writing-for-agents` when it's installed.
- **Description**: once the PR merges, prove it in a fresh T3 child task (`delegate_task`
  with a prompt that should trigger it), by finding the `Base directory for this skill:`
  line in that child's session log. Until then it stays ⬜ open in the report.
- **Mechanism**: build it, then prove it once. Trigger the hook, run the lint on the
  bad case, or run the script. Delete the prose it replaces in the same commit.
- **Note** or **Upstream**: run the `addystack` skill's Note job (a step only this user
  wants, written to their notes for that skill) or its Upstream job (a draft PR to the
  kit for its maintainer to review), with the row's proposal and evidence. Its preview
  and the user's okay replace this step's branch and commit.
- **Target repo**: run `correct` in that repo with the row's turn quotes, commit SHAs,
  and digest path. It builds and commits the check there, so reflect builds nothing for
  the row.
- **Shared files**: when the repo has a sync step for a shared file (such as
  `scripts/sync-format.sh`), run it and its check.
- **Evals**: when the repo has evals for the skill (such as `evals/<skill>/`), name the
  one that covers the change, so the user can rerun it.

**Done when:** every picked row is committed on the draft PR, written as a built note,
opened as an upstream draft PR, backed up and named (outside a repo), or reported as
blocked.

## 6. Report

````markdown
✅ **In gh-stack repos, `git push` stops and points to `gh stack push`.**

```text
$ git push
This repo pushes through gh stack, so `git push` is blocked: use `gh stack push` …
```

- Also applied: build names the verification skill; open-pr triggers on "PR body".
- Skipped: the `tdd` lesson, since that skill is an installed copy.

<details><summary>Items and checks: ⚠️ 1 eval not rerun · ✅ 3 applied · ⬜ 1 skipped</summary>

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | `build`: Run it names the verification skill | ✅ | `a1b2c3d` |
| 2 | `open-pr`: description triggers on "update the PR body" | ✅ | `d4e5f6a` |
| 3 | hook blocks `git push` in gh-stack repos | ✅ | `b7c8d9e` |
| 4 | `tdd` lesson needs a fork first (installed copy) | ⬜ skipped | — |

⚠️ `evals/build/` not rerun for 1 · ✅ evidence checked for 3/3 rows · ✅ hook blocked
`git push` in a test run

</details>
````

**Done when:** every Accepted and Mechanisms row is applied, skipped by the user, or
blocked, and each applied row has its own commit or named path.

Adapted from Lauren Tan's `reflect` in pstack (MIT); see [NOTICE](NOTICE).

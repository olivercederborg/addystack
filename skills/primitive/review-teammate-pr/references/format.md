<!-- Copy of shared/format.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Chat format

This file sets what an addystack skill reports. Each workflow skill points here from its
**Chat format** line. Lay it out, and the skill's examples, in the user's own reply
style (their global instructions, or the reply style they installed).

**Severity** for code findings. The verdict follows the worst: not done with any Blocker
or Cleanup, done when nothing needs fixing.

- **Blocker**: wrong behavior, a missing requirement, a failing check, or a broken rule.
- **Cleanup**: slop, scope creep, or a non-idiomatic pattern with a clear better form.
- **Optional**: what can wait outside the agreed outcome: a nicety with no correctness or
  maintenance cost, or a fix the slim-scope principle says waits. Any other cost the
  change caused or worsened is a Blocker or Cleanup, fixed in this change.

**Findings** follow the verdict, one line each, worst first, at most three visible (the
rest go in the fold with the evidence): ``**1** · Blocker · <what breaks, in a few plain
words> · `path:line` → <call>``. The call is **fix**, **follow-up**, or **skip** with a few-word
reason, unless the skill defines its own. A **follow-up** goes on the PR body's **Not in
scope** line, or the plan's before there's a PR. In a repo whose policy tracks
`issues` (`<kit>/bin/addystack policy --repo <checkout>`, as the router's Plan runs it), offer an issue as a `Next` option for one
that outlives the user's own PR. Drop a finding the change
didn't cause or worsen. A new path that drops what sibling code uses (an error's
reason, a retry flag) is this change's finding, even with unchanged text. When nobody
can hit it yet (a flag is off, no
users, or the real configured input can't trigger it, checked without printing
secrets), say so; it's Cleanup at most and needs no shim.

**Cards**: a decision uses the [decision card](views.md#decision-card-example). A fix that changes the flow or
design gets a finding card, and the worst one is the reply's shape, on the surface: a
small `diff` of the enclosing function under a first-line comment saying what breaks and
for whom. For a type-level finding, annotate the code with the inferred types (`^?`
comments, plus the runtime result when it differs), before and after. Any other card
goes in the fold: a bold `1 · <subject> → <call>` line, one or two sentences on what
breaks, for whom, and why, and its `diff`.

**Evidence**, one line per finding, in the reply's one fold:
`` `path:line` · verified by <how> · source: <source> ``. Add the login when someone
raised it, `doesn't hold: <why>` when a reviewer's claim is wrong, and `not checked:
<gap>` only for what can't be checked from here, such as a physical device. Check first
whatever the repo, installed source, docs, `--help`, a read-only production replica,
Executor, or a connected MCP server can answer.

**Lenses.** Before judging or writing code, load these once per session with the Skill
tool (or read them):

- `grounding`;
- the user's taste: the file their instructions name under Principles or Taste, or the
  kit's [taste](taste.md) when they name none;
- each of the repo policy's `lenses` (`<kit>/bin/addystack policy --repo <checkout>`, as the router's Plan runs it), a skill by
  name or a file by path, with its references for the areas the change touches;
- the repo's own convention skills for those areas, such as `*-grounding`,
  `*-conventions`, `*-convention-pass`, `code-structure`, `file-structure`, and
  `testing-guidelines`.

A lens matches when its description names a file, import, or boundary the diff touches,
and a matched lens always loads; `skip: <reason>` is only for one that matches nothing.
Until the lenses have run on the current head, shown in the checks as `✅ idioms (<each
lens loaded>)`, `a` runs them, and mark ready, approve, and post aren't options.

**Approval.** A step that needs the user's pick, go, or okay to push or post waits for
it, unless the user's instructions grant autonomy for that step. With autonomy, take the
recommended option, log it, and go on. A stop those instructions name still waits.

**Steps as todos.** Before following this skill's numbered steps, copy them into the
todo list in order, or, with no todo tool, into your progress messages. A step you don't
do stays as `skip: <reason>`, so a skipped check shows instead of vanishing.

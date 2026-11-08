# Change

One setting, such as "make agents stop before merging in `~/code/acme`".

## 1. Look up

- **Where it applies.** One repo or folder of repos becomes a `policy.repos[]` rule;
  every checkout becomes `policy.defaults`; anything else is its own top-level key.
  For a repo, find its top level (`git -C <path> rev-parse --show-toplevel`) and origin
  (`git -C <path> remote get-url origin`). Match by `path` glob for a folder of
  checkouts, or by `remote` regex when the repo has several checkouts or worktrees.
- **Which field.** Map the request onto the schema's fields by their
  `markdownDescription`. Stop-and-wait requests land on `planning` (plan gates) and
  `trust` (how far a verified stack goes: `draft` stops before ready and merge);
  `pushVia` picks `git` or `gh-stack`.
- **Today's value.** Run `<kit>/bin/addystack policy --repo <path> --explain`: the
  fields in force and the rule each came from. A repo's own `.agents/addystack.jsonc`
  can only make a field stricter, so a looser value the user asks for can't beat it;
  say so.
- **An existing rule** whose `match` is the same: edit that rule rather than add a
  second.

When no field expresses the request, such as "stop before pushing" (no field
holds pushes back; `trust: draft` still pushes a draft stack), say which field comes
closest and what it does, then offer the paths that can: a Note on the skill that does
the step, or a line in the user's own instructions file (`instructions` in the config,
usually `global.md`). Write nothing until the user picks one.

## 2. Ask

Only what the lookup left open: which repo when the request didn't name one, or which
of two fields when both fit.

## 3. Preview

Copy the config to `.addystack.proposed.jsonc` beside it, make the edit there, keeping
comments and every other key, and validate it with
`ADDYSTACK_CONFIG=<proposal> <kit>/bin/addystack print-config`. Show:

- `diff -u` of the config and the proposal.
- The field's value before and after, for the repo the user named. `policy` reads the
  built state, not a config, so build the proposal into a scratch folder first:
  `ADDYSTACK_CONFIG=<proposal> ADDYSTACK_STATE=<tmp>/state ADDYSTACK_CLAUDE_MD=<tmp>/CLAUDE.md ADDYSTACK_CODEX_MD=<tmp>/AGENTS.md <kit>/bin/addystack build`,
  then `ADDYSTACK_CONFIG=<proposal> ADDYSTACK_STATE=<tmp>/state <kit>/bin/addystack policy --repo <path> --explain`
  for after, and the same `policy` command without the overrides for before.
- `ADDYSTACK_CONFIG=<proposal> <kit>/bin/addystack install --dry-run`: each file the
  write would change, the host settings for a `hooks` or `hosts` key and the built
  instruction files.

Leave the config untouched until the user okays this preview.

## 4. Write

Keep the old config as `addystack.jsonc.bak`, move the proposal over it, then run
`<kit>/bin/addystack install`, which applies hooks and hosts to the host settings,
builds, and runs `doctor`. Prove a `policy` change with `policy --repo <path> --explain`
showing the new value and the rule that set it, and any other key with `print-config`.

**Done when:** `--explain` (or `print-config`) shows the new value, and `doctor` passes or
its failure is in the reply with its fix.

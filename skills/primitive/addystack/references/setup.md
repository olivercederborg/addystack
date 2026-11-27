# Set up

First run, or a re-run of one section ("set up my replies"). A re-run asks only that
section's questions and keeps every other key, the way `npm init` keeps what's set.

## 1. Look up

Run each probe and keep its answer as the default:

| Section | Key | Default, and how to find it |
|---|---|---|
| identity | `identity.name` | first word of `git config user.name` |
| identity | `identity.github` | `gh api user -q .login`, or `null` |
| hosts | `hosts.claude`, `hosts.codex`, `hosts.agents`, `hosts.t3` | `command -v claude`, `command -v codex`, `~/.agents/AGENTS.md` exists, `~/.t3` exists |
| hosts | `hosts.machines` | none |
| policy | `policy.defaults.planning` | `gated` |
| policy | `policy.defaults.trust` | `draft` |
| policy | `policy.repos[]` | none; offer a rule for each folder of personal repos the user names |
| replies | `replies.style` | `own` when `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md` has content, else the kit's style (the schema's other value) |
| replies | `replies.next` | `off` |
| judgment | `judgment.principles.preset` | `addystack` |
| judgment | `judgment.taste` | `null` |
| hooks | `hooks.preset` | `recommended` |

Also read the current config when there is one; its values replace these defaults.

## 2. Ask

Ask about the keys a probe couldn't settle, in rounds of at most 4, policy first, since
it decides when agents stop. Read each key's `markdownDescription` in the schema to word
its options. Confirm the probed values in one question at the end ("These look right?"),
not one each.

## 3. Preview

Build the proposal as `.addystack.proposed.jsonc` beside the config, so files it names,
such as `taste.md`, resolve from the same folder:

- No config yet: `ADDYSTACK_CONFIG=<config folder>/.addystack.proposed.jsonc <kit>/bin/addystack init --yes`
  writes the detected defaults there; then merge in the answers.
- A config exists: copy it and merge the answers into the copy, keeping its comments and
  every key you didn't ask about.

Validate it with `ADDYSTACK_CONFIG=<proposal> <kit>/bin/addystack print-config`, which
names each bad key path. Show `diff -u` of the current config (or `/dev/null`) and the
proposal.

## 4. Write

On the user's okay, keep the old config as `addystack.jsonc.bak` and move the proposal
over it. Then show `<kit>/bin/addystack install --dry-run`: the hooks it merges into each
host's settings, the instruction files it moves into `global.md`, the work-verifier agent
link, and the built files' diffs. That preview is the approval for `<kit>/bin/addystack install`, which builds and
runs `doctor`. On a doctor failure, report the failing check and its `fix:` line, and
stop.

**Done when:** `doctor` passes, or its failing check is in the reply with its fix.

---
name: addystack
description: "Sets up and changes the user's addystack install: first-run setup, a setting, a note on a core skill, an update, or a kit change for everyone. Use for /addystack, when asked to change how agents work in a repo, to add a step to a core skill, why an agent stopped or waited, or to update addystack."
metadata:
  layer: primitive
---

# addystack

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

The user's front door to their addystack install. Every job takes the same four steps:

1. **Look up** every value you can: the config, the tool's output, git, the files on
   disk. A question whose answer a command can give is legwork, not a question.
2. **Ask** only what's left, at most 4 questions a round (`AskUserQuestion` in Claude
   Code, numbered questions in Codex), each with the looked-up default first.
3. **Preview** the exact change: `diff -u` of each file, and the tool's dry run when it
   has one. The user's okay on the preview is the approval for that write.
4. **Write**, then **validate** with the tool, and show the result that proves it.

**The tool.** `<kit>` is this skill's own folder, which holds `bin/addystack` and the
kit's `CHANGELOG.md`. Run `<kit>/bin/addystack --help` for its commands;
each one runs without a terminal. The config is `~/.config/addystack/addystack.jsonc`
(`ADDYSTACK_CONFIG` overrides it), and its keys are documented in
`<kit>/schema/v1.json`, each with a `markdownDescription`. Read the schema for a key's
meaning and values; never guess one.

## Jobs

Name the job from the request, then read its file before the first command:

| Job | When | Read |
|---|---|---|
| **Set up** | No config yet, or "set up addystack" | [setup.md](references/setup.md) |
| **Change** | A setting: "make agents stop before merging in repo X", "use gh stack here" | [change.md](references/change.md) |
| **Note** | An added step for one core skill: "verify-work should also run X" | [note.md](references/note.md) |
| **Explain** | "Why did it stop?", "why is this repo gated?" | [explain.md](references/explain.md) |
| **Update** | "Update addystack" | [update.md](references/update.md) |
| **Upstream** | A change to the kit itself that would help every user | [upstream.md](references/upstream.md) |

A request can need two jobs, such as Explain, then Change. Run them in that order.

**Done when:** the job's own file says it's done, and the reply shows what proves it.

## What addystack doesn't own

The config folder holds only addystack's own settings. A personal skill installs the
standard way, with `npx skills add <source> -g`, and a personal hook goes in the host's
own settings (`~/.claude/settings.json`, `~/.codex/hooks.json`) beside the kit's, which
`addystack install` keeps. Point the user there and write nothing for it.

A core skill stays as the kit ships it. Dropping a step means not installing that skill
and writing one of their own under another name; adding one is a Note.

## Report

Lead with what changed and the command output that proves it, such as the new
`policy --explain` fields or `doctor`'s result. List each file written with its path and
any backup. When the job stopped before writing, say what's waiting on the user.

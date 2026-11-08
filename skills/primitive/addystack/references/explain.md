# Explain

"Why did it stop?", "why is this repo gated?" Answer from the tool's output, never from
memory of the config.

## 1. Look up

Find the checkout the work landed in: the path the user names, the stopped thread's
working folder, or the current one. Run:

```bash
<kit>/bin/addystack policy --repo <checkout> --explain
```

It prints the fields in force (`planning`, `trust`, `pushVia`, `issues`, `lenses`,
`verifySkill`, `decisionsSection`), `matched` (the sources that set them, in order), and
`explain`: each matched rule's `match` and `set`, plus `repoFile` and `unresolved` when
they apply.

Read `matched` this way:

| Source | What it is |
|---|---|
| none | `policy.defaults` in the config, over the kit's defaults |
| `user#<n>` | `policy.repos[<n>]` in the config, counting from 0 |
| `repo-file` | the repo's own `.agents/addystack.jsonc`; each field takes the stricter of it and the config |
| `repo-file-invalid` | that file couldn't be read or isn't valid: every field is its strictest value |
| `unresolved` | the lookup couldn't finish, as when the origin remote can't be read: every field is its strictest value |

A stderr line saying `resolved.json` is missing means nothing is built yet, so these are
the kit's defaults.

## 2. Answer

Tie the stop to the field that caused it:

- **`planning: gated`**: the agent waits at the plan gates, such as the scope questions,
  the architecture pick, and the go that starts the build.
- **`trust`**: `draft` stops at a draft stack; `gate` marks ready and merges once the
  merge gate allows it; `merge-on-go` merges when the user's go names merging.
- **`pushVia: gh-stack`**: a hook blocks `git push` and the agent pushes with `gh stack`.

Name the source: the rule's index and its `match`, or the repo file's path. When the
repo file made a field stricter, say the user's config can't loosen it there.

Some stops come from no field: a production write, a message to a person, a missing
credential, a force-push to a shared branch. The instructions' **Stops** list holds
them, the same in every repo. Say so when that's the cause.

When the user wants a different result, offer the Change that would give it, as the
first next step.

**Done when:** the reply names the field, its value, and the source that set it, quoting
the `--explain` output, or names the Stop that applies whatever the policy.

# Evidence by change type

Tests pass while a UI, a migration, or a deploy still fails the way its type fails. Each
kind below names the proof that catches that failure. [`scripts/verdicts.py
classify`](../scripts/verdicts.py) matches text, not syntax, so its kinds are a floor:
an exported declaration that changed gets the contract diff, flagged or not.

Save artifacts in `$(git rev-parse --path-format=absolute --git-common-dir)/verify-work/evidence/<head-sha>/`,
writing with shell redirection or the capture tool, and pass each as `--evidence KIND=PATH`. Show every artifact in the verdict, Done or Not
done, as its kind's **Show** line says.

## ui

Capture each changed state, and every screen or route the claim covers, not only the
changed ones: "the redesign is complete" covers the whole app. Web at desktop (1440px)
and 390px. Mobile at device size, through the Xcode MCP or a simulator. Light and dark
when the app has both. Drive it with the project's `verify-<app>` skill (the repo policy's
`verifySkill`) or `capture-ui-artifacts`.

Show: every capture as a Markdown image labeled with its size, `![390px](path)`. Many
captures go in the reply's one fold, under a bold label per route or state.

Ref: each image or video file (`.png .jpg .jpeg .webp .gif .mp4 .webm .mov`), whose
first bytes match its type.

## parity

For a refactor, migration, port, or upgrade that keeps behavior. Run the same tests or
fixture inputs on base and head, with base in a `git worktree add /tmp/<name>
<base-sha>`, so the reviewed tree stays as it is. Compare outcomes: accept or reject,
status, branch taken, rows written, outbound payloads. Changed message text, log format,
and doc wording are notes, not breaks.

Show: a table with a row per input, with base's and head's outcome for each, however
long the log.

Ref: the log or diff of both runs.

## contract

For an API schema, a shared format, or an exported declaration that changed or went
away. Diff the OpenAPI or JSON Schema, or the exported declarations (for TypeScript,
`tsc --declaration --emitDeclarationOnly` on both). Check who can call it before
rating a break.

Show: each changed hunk in a `diff` block, with each change called out under it.

Ref: the diff.

## mutants

For money, auth, and migration paths. Make 3 to 5 mutants in the changed functions, such
as a flipped condition or a dropped branch or clause. Run the tests against each in a
temp worktree, and log one line per mutant: `killed: <mutant>` when a test fails,
`survived: <mutant>` when they all pass. A survivor is a Blocker on these paths and a
Cleanup elsewhere; the recorder refuses Done while the log has one.

Show: the `killed:` and `survived:` lines, as logged.

Ref: the log, with at least 3 such lines.

## deploy

For a claim that the change is live. Name the URL or version actually serving it, and
check it with a content or version marker, not only a 200.

Show: the response, with its version marker.

Ref: the URL, or a file holding the response.

## toolchain

For a change to the config a dev server or bundler loads, whose plugins run on every
module in local dev, where CI's production build never goes. Measure the same cold
workload at base and head with
[`scripts/dev-cost.py`](../scripts/dev-cost.py): a worktree of each, the repo's own dev
command, its bundler cache in `--clean`, and one or two real pages in `--path`. Run
base, head, base, head, appending each printed line to one log. A mean that grows 20% or
more in peak RSS or processes is a Blocker, and the recorder refuses Done until the PR
fixes it or the log gets an `accepted: <why>` line the PR names. A dev server that needs
what isn't here, such as a secret, gets `not-run:<reason>`.

Show: the `base:` and `head:` lines, as logged.

Ref: the log.

## idiom

For code the change adds or edits outside tests. Ground each non-trivial pattern it
introduces, such as a library API, a framework hook, or an error-handling or
concurrency construct, with [grounding](grounding.md): is it how the library's authors
intend it at the installed version? Repo precedent shows consistency, not idiom. A
pattern that doesn't hold is a finding. Write one line per pattern, as
`<pattern> · <how verified> · source: <URL>`:

```text
`Effect.retry` with `Schedule.exponential` · verified by the retry test · source: https://effect.website/docs/error-management/retrying/
```

A change with no such pattern, such as a rename, writes one line instead: `none: <why>`.

Show: the lines, as written.

Ref: the file. Each line opens with a pattern and has a `source:` URL, or the file is
one `none:` line.

## Missing or not run

Missing evidence is 🔴 or 🟡 **Not done**, with a finding naming what's missing. A check
that can't run here, such as with no simulator or no credential, is 🟡 **Not verified**:
record it as `--evidence <kind>=not-run:<reason>` with `--verdict not-verified`. A
`not-run:` ref never backs Done.

# architect evals

Run `evals/verify-work/setup.sh /tmp/architect-eval`, then
`git checkout -b feature/summary` inside it. Start a fresh Claude Code session in T3 Code there, with
Codex enabled as a T3 provider, and give the agent this agreed plan as earlier conversation:

- **Goal:** add a monthly summary (`totals per currency for a month`) that reuses the
  export's date-range filter instead of copying it.
- **Decisions:** inclusive date range · totals keep two decimals · plain TypeScript,
  no new dependencies.
- **Not in scope:** JSON output · scheduling · changing the CSV columns.

Then send "architect it".

Grade each assertion PASS or FAIL, and quote the evidence:

- **Trace:** the touched modules, their current interfaces, and their callers are named
  before any sketch.
- **Three shapes:** three candidates differ in module split, ownership, or data shape.
  The second came from Codex and the third from an Opus 5.5 child at high effort, both
  as T3 child tasks, or the report says which couldn't run.
- **Usage first:** the recommended candidate is the reply's one snippet, and each other
  candidate is one note, with its code in the fold. Each sketch shows the caller's
  usage with its signatures, and has a call tree. Evidence is in the fold.
- **Screen:** each candidate was checked for shallow modules, leaked internals,
  temporal splits, and pass-throughs, with any revision named.
- **Gate:** nothing is written to the repo before the user approves a shape.
- **Contract:** after approval, one commit adds the new types and signatures with
  `not implemented` bodies, and `bun test` still passes. Reshaping `export.ts` is a
  before → after line in the plan, not an edit, and no function body is implemented.
- **Hand-off:** the report ends with a `Next` list led by a bold `a` → build.

## Trigger check

In a fresh session, after a `scope-grill` summary whose decisions add a new module,
pick its `a`. The session log should show `architect` loaded, not `build`.

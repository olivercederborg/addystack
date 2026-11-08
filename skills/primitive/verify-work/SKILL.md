---
name: verify-work
description: "Checks whether a branch or PR is done, in a fresh verifier, and records Done for the merge gate. Use when asked if work is done, production-ready, idiomatic, or clean, or whether anything is left to improve."
compatibility: Requires git. Uses gh for PR metadata when available.
context: fork
agent: work-verifier
background: false
metadata:
  layer: primitive
---

# Verify work

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

verify-work judges one diff against what was asked, shows the proof for each claim, and
records the verdict the merge gate reads. It reports; the caller fixes.

## 1. Pin the scope

- **Target**: the PR or branch in the arguments, else the checked-out branch and its PR.
  With neither, stop and say what's missing: a target you go looking for is often
  someone else's work.
- **Diff**: for a PR, run `scripts/github.sh target N`. When `local_head` matches
  `head_sha`, review `base_sha...head_sha`, the commits the merge gate checks; otherwise
  review `<parent>...HEAD`, and the verdict covers the PR only once that head is pushed
  unchanged. For a branch with no PR, review the `base_sha...head_sha` that
  `target --branch B --parent P` prints. Never check anything out. Only this diff is in
  scope; other code is context.
- **Intent**: the linked issue or spec, the PR description, and the arguments, with any
  **Not in scope** list. Missing intent is a finding.
- **Evidence kinds**: `scripts/verdicts.py classify <base-sha> <head-sha>`, plus what the
  intent implies: ui for anything users see, parity for a refactor or migration that
  claims no behavior change, contract for a shared format, deploy for a claim that it's
  live, toolchain for a new bundler plugin or dev-server dependency.

**Done when:** the diff, its base, the intended outcome, and the evidence kinds are known.

## 2. Check

A Blocker or Cleanup needs a failure you can show, cited by file:line: a check that fails
at the head, an input and its wrong result, a doc line the change made false, or a rule
it breaks. Anything weaker is Optional.

- **Scope**: everything asked, nothing more. Speculative options, future-proof
  abstractions, extra endpoints, and code for a Not in scope item are scope creep
  (Cleanup).
- **Idiom**: an upstream source for each non-trivial pattern, per evidence's
  [idiom](references/evidence.md#idiom) kind.
- **Standards**: the repo's conventions and the user's standards, through the chat
  format's **Lenses**. A term `CONTEXT.md`'s glossary says to avoid is a Cleanup.
- **Slop**: the list below, plus `tidy`'s criteria when installed.
- **Tests**: each protects behavior that could regress, through the interface rather
  than past it (such as a direct database query), with no duplicates.
- **Placement**: new code lives in the module that owns it, and a new abstraction has two
  real adapters (`codebase-design` when installed). Read git blame before flagging odd
  code: it may be intentional.
- **Root cause**: each fix removes the cause. A workaround gets a card with the
  root-cause option, even when the spec prescribed it.
- **Nearby**: up to three small Optional improvements, in the files the diff touches.
- **Verification**: the focused typecheck, lint, and tests for the touched packages,
  judged by exit code. Run a new or changed test, eval, or fixture once: its setup must
  reach the state the code assumes, and a failing assertion is checked against the
  fixture before the code changes.
- **Real run**: run the change once through each real boundary it crosses, since tests
  with fakes pass while the real thing breaks. A served client: a real one, such as an
  MCP or OAuth client that reads the server's own challenge. A database: a migrated copy
  of real data. State that outlives a request (caches, pooled clients, sync): the flow
  twice. Data another tool writes (logs, exports, API responses): real local inputs,
  anomalies counted. Paid or rate-limited calls: counted across the user's flow. A
  toolchain, SDK, or lockfile change: one real build on each hosted builder that uses
  it. UI: the project's `verify-<app>` skill. Cite each run's command and result. A
  boundary with no real run is a Blocker; one that needs what isn't here, such as a
  physical device or production access, makes the verdict 🟡 **Not verified**, naming
  that run.
- **Evidence**: each kind from step 1 has the proof [evidence](references/evidence.md)
  names, saved for the record.
- **Decisions**: each behavior change has a matching row in the PR's Decisions table or
  the log's `--pr` rows, or it's a Cleanup. In a parity change, an `agent` behavior row
  is a regression candidate.
- **PR**: the title and description match the diff and the repo's template. Calling it
  mergeable needs `scripts/github.sh mergeable N` ([GitHub commands](references/github.md))
  to say `mergeable: yes` at the current head.

### Slop

- Tests that assert nothing real: a mock returning what it was told, or a restatement
  of the implementation.
- Wrappers that only forward, and vague verbs (`prepare*`, `handle*`, `process*`, `do*`).
- Comments that narrate the change or restate the code, and leftover debug output.
- Guards for states the types rule out, and dead code, including compatibility paths
  for code that never shipped.
- Names that don't say what they hold, fields that always travel together, and one
  change spread across many files.
- New suppressions and casts. List the candidates, then read each in context:

  ```bash
  git diff -U0 <base>...<head> -- '*.[cm]ts' '*.ts' '*.tsx' '*.[cm]js' '*.js' '*.jsx' |
    grep -E '^\+.*( as\b|eslint-disable|@ts-(expect-error|ignore))' |
    grep -vE '^\+\s*(\*|import |export \{|export \* )'
  ```

  A new one other than `as const`, not a moved or kept line, is a Cleanup unless the PR
  body names its approval.

**Done when:** every lens has covered the whole diff and every check has run.

## 3. Verdict

Lead with the verdict: 🔴 **Not done** with any Blocker, 🟡 **Not done** with only
Cleanups, 🟡 **Not verified** when the only gap is a real run that can't happen here, and
✅ **Done** when nothing, or only Optional findings, remain. Say what breaks in plain
words, and show the worst finding's code as the reply's one snippet.

The fold holds what a reader and a re-run need: the base and head checked, the checks,
one evidence line per finding, the fix diffs, and every artifact itself (each image,
table, or log, as [evidence](references/evidence.md) shows its kind), never a path,
folder, or count in its place, so the reader sees the proof without opening a file. A
Done shows its proof the same way, since that proof is what the reader trusts.

````markdown
🔴 **Not done: a retry after finalizing never publishes the export.**

```ts
// src/export.ts: a retry finds the job finalized and returns early
if (job.finalized) return job;   // ← publish(job) below never runs
await publish(job);
```

- **1** · Blocker · a retry after finalizing skips publish · `export.ts:12` → fix
- **2** · Cleanup · the tests still pass with `publish` deleted · `export.test.ts:30` → fix
- **3** · Optional · `prepareRows` only forwards · `export.ts:4` → skip: removed in #4620

<details><summary>Checks: ❌ tests 11/12 · ✅ 3 passed, and evidence</summary>

Checked base `a1b2c3d` · head `e4f5a6b`

❌ tests 11/12 · ✅ typecheck · ✅ lint · ✅ idioms (the repo's lenses, grounding, taste)

- **1** · `src/export.ts:12` · verified by a failing test at the PR head · source: retry in `payments.ts`

```json
{"patch_id": "7c41d09e5b2a8f63e1d47a90c2b5e8f13a6d9c04", "reviewed": {"base": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678", "head": "e4f5a6b7c8d90123456789abcdef0123456789ab"}, "recorded_at": "2026-10-24T09:12:40Z", "verifier": {"session_id": "s-31f0", "agent_id": "a-9c2e", "agent_type": "work-verifier"}, "verdict": "not-done", "evidence": {}, "findings": ["1 · Blocker · a retry after finalizing skips publish · export.ts:12 → fix", "2 · Cleanup · the tests still pass with publish deleted · export.test.ts:30 → fix", "3 · Optional · prepareRows only forwards · export.ts:4 → skip: removed in #4620"], "required": {}}
```

</details>
````

**Record** every verdict with `scripts/record-verdict.sh <base-sha> <head-sha> --branch
<branch>` and paste its receipt verbatim in the fold as a `json` block. A Not done adds
`--verdict not-done` with one `--finding` per finding line, and a Not verified
`--verdict not-verified` with a `--finding` naming the run it couldn't do. Pass each artifact as `--evidence KIND=REF` and each kind
the intent implies as `--require KIND`: the recorder refuses Done while a needed kind
lacks a ref. The merge gate reads the latest verdict for the exact diff, so a Not done
revokes an earlier Done. When the recorder refuses because this isn't a fresh
work-verifier, start one with these steps and paste its receipt.

PR title or description text blocks only through a check that fails on it, such as a
required issue link. Otherwise it keeps a Done, as a **Fix before push** line in the fold
and a `--finding`, naming each line to change. The caller fixes it with `open-pr`'s sync
and needs no new verdict, since the patch-id doesn't cover PR text.

**Done when:** the verdict is given and recorded.

## 4. Stop and hand back

verify-work stops at the recorded verdict, with the code as it found it, and hands back
the verdict, the findings with their calls, and what the caller does next: on Not done,
each fix, committed on the branch that owns it (the lowest, in a stack), then a
re-check; on Not verified, the run still owed; on Done, the scope checked and which of
review-loop and open-pr haven't run on this head.

## 5. Re-check

A run after an earlier verdict ("anything else?", "is it done now?", after fixes or a
restack) checks the **delta**: what changed since the head that verdict checked. Take
that verdict's base, head, and findings from the verifier's record, the last line of
`scripts/github.sh target`, never from the caller's account. With `last: none`, or when
the user asks for a full pass, run steps 1 to 4. When the line has `known`, the verdict
stands: say why and stop there, reading no new code and recording nothing, unless it's a
Not verified whose run can now happen.

1. **Delta**: pin the base and head as step 1 does. On the recorded base, with the
   recorded head an ancestor, read `git diff <last head> <head>`. On a new base, read
   `git range-diff <last base>..<last head> <base>..<head>`: each new or changed commit
   is in the delta, including ones the new base brings in. Read the code the delta
   calls, with the lenses it matches. Run steps 1 to 4 instead when neither holds, or
   when range-diff can't see the change: a dropped commit (`<`), a merge commit in
   either range (`git rev-list --merges`), or a binary file (`-` in
   `git diff --numstat`).
2. **Checks**: the Verification checks, a trial merge with the base branch's tip
   (`git merge-tree --write-tree <tip> <head>` exits 0; the tip is `origin/<base branch>`
   after a fetch, or the parent layer in an unpushed stack), and the PR lens.
3. **Blockers**: rerun the run or test that showed each fixed Blocker. A delta crossing
   a boundary the last real runs didn't cover gets its own Real run, as does each run
   that verdict couldn't do.
4. **Earlier findings**: each one marked fix is gone at the head, with every other
   instance of its class the change caused, searched across the repo. Name each fixed one
   as gone, and keep one still there as a finding line under its old number. Ones it
   marked follow-up or skip stay settled, and aren't raised again.

Report the re-check's verdict as step 3 does, with its numbered finding lines and receipt.

With no Blocker or Cleanup left, new or earlier, and no run owed, say "Nothing further",
name the delta checked, and record Done for the new head. Optional finds go on one
folded line, `Also seen (Optional): <a few words each>`, without numbers or cards; hand
one back as a fix only when it carries a real risk, such as a security gap.

**Done when:** the verdict is given and recorded, or a `known` re-check stopped.

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

## 1. Pin the scope

- **Target**: the PR or branch in the arguments, or else the checked-out branch, with
  its PR if it has one. With neither, stop and say what's missing, since a target you
  search for is often someone else's work.
- **Diff**: for a PR, run `scripts/github.sh target N`. When `local_head` matches
  `head_sha`, diff `base_sha...head_sha`, the commits the merge gate checks. Otherwise,
  diff `<parent>...HEAD` and verify that head; the verdict covers the PR only if that
  head is pushed unchanged. For a branch with no PR, diff the `base_sha...head_sha` that
  `target --branch B --parent P` prints. Never check anything out. Only this diff is in
  scope, plus the **Nearby** lens; other code is context.
- **Intent**: the linked issue or spec, the PR description, and the intent in the
  arguments, including any **Not in scope** list. Missing intent is a finding.
- **Evidence**: run `scripts/verdicts.py classify <base-sha> <head-sha>` for the kinds of
  evidence the change's type needs. Add the kinds the intent implies: ui for a change to
  what users see, parity for a refactor or migration that claims no behavior change,
  contract for a shared format, deploy for a claim that it's live, toolchain for an added
  bundler plugin or dev-server dependency.

**Done when:** the diff, its base, the intended outcome, and the evidence kinds are known.

## 2. Check

A Blocker or Cleanup needs a failure you can show: a run or check that fails at the head,
an input and the wrong result it gets, a doc line the change made false with the case
it gets wrong, or a rule it breaks, cited by file:line from the repo, the user's
standards, or a lens below that names a severity. A finding with none of these is
Optional, whatever kind the chat format's severity list gives it.

| Lens | Question |
|---|---|
| **Scope** | Does it do everything asked, and nothing more? Speculative options, future-proof abstractions, and extra endpoints are scope creep (Cleanup), as is code for a **Not in scope** item unless the user moves it in. |
| **Idiom** | The `idiom` kind in [evidence](references/evidence.md#idiom): an upstream source for each non-trivial pattern. |
| **Standards** | Does it follow the repo's conventions and the user's coding standards, per the chat format's **Lenses**, the repo policy's included? Names use the glossary's terms from `CONTEXT.md`; a term the glossary says to avoid is a Cleanup. |
| **Slop** | Check the slop list below, and apply `tidy`'s criteria when installed. |
| **Tests** | Does each test protect behavior that could regress, with no more tests than needed, going through the interface, not past it (such as a direct database query)? |
| **Placement** | Does new code live in the module or domain that owns it? Is a new port or abstraction backed by two real adapters? Use `codebase-design` when installed. Before flagging odd code, check git blame and its issue: it may be intentional. |
| **Root cause** | Does each fix remove the cause, or route around it? A workaround gets a card with the root-cause option, even when the spec prescribed it. |
| **Nearby** | Can the files the diff touches be left cleaner? Report up to three small Optional improvements, within those files only. |
| **Verification** | Run the repo's focused typecheck, lint, and tests for the touched packages. A check passes on its exit code, never on grepped output. When the diff adds or changes a test, eval, or fixture, run it once: its setup must reach the start state the code assumes, and a failing assertion is checked against the fixture before the code changes. |
| **Real run** | Did the change run once through each real boundary it crosses? Tests with fakes don't count: they pass while the real thing breaks. A client the code serves: drive it with a real client, such as an MCP or OAuth client that reads the server's own challenge. A database: run on a migrated copy of real data. State that outlives one request (caches, pooled clients, sync): run the flow twice. Data another tool writes (logs, exports, API responses): run over real local inputs and count anomalies. Paid or rate-limited calls: count them across the user's flow. A toolchain, SDK, package-manager, or lockfile change: one real build on each hosted builder that consumes it, such as a deploy preview's install or an EAS cloud build. UI: drive it with the project's `verify-<app>` skill. Cite each run's command and what it showed. A boundary with no real run is a Blocker. A run needing what isn't here, such as a physical device or production access, makes the verdict 🟡 **Not verified**, naming that run. |
| **Evidence** | Does each kind from step 1 have the proof [evidence](references/evidence.md) names, saved for the record? |
| **Decisions** | Does each behavior change have a row in the PR's Decisions table or the log's `--pr` rows, not only a Skim entry, and does it match its code? Either miss is a Cleanup. In a parity change, an `agent` behavior row is a regression candidate. |
| **PR** | Do the title and description match the diff and follow the repo's PR template? A verdict that the PR can merge cites `scripts/github.sh mergeable N` ([GitHub commands](references/github.md)) saying `mergeable: yes` at the current head. |

### Slop

- **Tests that assert nothing real**: they check a mock returns what it was told, restate
  the implementation, or cover the same path twice.
- **Wrappers that only forward**: a function or type that adds nothing over what it
  wraps.
- **Vague verb prefixes**: `prepare*`, `handle*`, `process*`, `do*`, where a precise verb
  exists.
- **Leftover narration**: comments that retell the change or restate the code.
- **New suppressions and casts**: list the candidates with

  ```bash
  git diff -U0 <base>...<head> -- '*.[cm]ts' '*.ts' '*.tsx' '*.[cm]js' '*.js' '*.jsx' |
    grep -E '^\+.*( as\b|eslint-disable|@ts-(expect-error|ignore))' |
    grep -vE '^\+\s*(\*|import |export \{|export \* )'
  ```

  Read each in context. A suppression or type assertion other than `as const` in code
  that the base didn't already have, rather than a moved or kept line, is a Cleanup,
  unless the PR body names its approval.
- **Impossible-state guards**: checks for states the types already rule out.
- **Dead code**: unused exports, parameters, branches, and leftover compatibility paths
  for code that never shipped.
- **Leftover debug output**: debug logs, tagged or not.
- **Heuristics**:
  - **Mysterious names**: a name that doesn't say what it holds or does.
  - **Data clumps**: the same fields keep travelling together and want to be one type.
  - **Shotgun surgery**: one logical change forces edits across many files.

**Done when:** every lens has been applied to the whole diff and every check has run.

## 3. Verdict

For example:

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

---

**Next**

- **`a` → fix 1 and 2, one commit each, then verify again** · *recommended*
````

- **Verdict first**, as the headline: 🔴 **Not done** with any Blocker,
  🟡 **Not done** with only Cleanups, 🟡 **Not verified** when the only gap is a real run
  that can't happen here, and ✅ **Done** when nothing or only Optional findings remain.
  PR title or description text blocks only through a check that fails on it, such as a
  required issue link. Otherwise it keeps a Done, as a **Fix before push** line in the
  fold, recorded as a `--finding`, naming each line to change. The caller fixes it
  with `open-pr`'s sync and doesn't run verify-work for it, since the patch-id doesn't
  cover PR text. Say what breaks in plain words. The shape is the snippet of the worst finding's code.
- **The fold**: the base and head SHAs checked, the checks line, one evidence line per
  finding, the fix diffs, and every artifact passed as `--evidence`; a re-run needs
  them. Show each artifact itself, never a path, folder, or count in its place, as
  [evidence](references/evidence.md) shows its kind, so the reader sees the proof
  without opening a file. A Done shows them as a Not done does, since its proof is what
  the reader trusts.
- **When done**: name the scope checked, and end with the `Next` options review-loop
  and open-pr, leaving out any that already ran on the current head.
- **Record** every verdict with `scripts/record-verdict.sh <base-sha> <head-sha>
  --branch <branch>`, the commits and branch you checked, and paste its receipt verbatim
  in the fold as a `json` block. For 🔴 or 🟡 **Not done**, add `--verdict not-done` and
  one `--finding` per finding line. For 🟡 **Not verified**, add `--verdict not-verified`
  and a `--finding` naming the real run you couldn't do. Pass each artifact as
  `--evidence KIND=REF`, and each kind the intent implies as `--require KIND`: the
  recorder refuses Done while a kind the change needs has no ref that backs it. The
  merge gate reads the latest verdict for the PR's exact diff, so a Not done revokes an
  earlier Done.

## 4. Fixes and re-checks

Fixes are the caller's: offer each as a `Next` option that commits it on the branch that
owns it (the lowest, in a stack), then runs verify-work again.

A re-run ("anything else?", "nothing left?", "is that really done?", after fixes, or
after a restack) is a **quick re-check** of the **delta**: what changed since the head
the last verdict checked. That verdict's base, head, and findings come only from the
verifier's record: `scripts/github.sh target`'s last line. A caller's account of it is
context, not a baseline. With no record (`last: none`), or when the user asks for a full
pass, run steps 1 to 3 instead. Otherwise, when that line has `known`, say why and stop,
unless it's a Not verified whose run can now happen.

1. **Delta**: pin the base and head as step 1 does. On the recorded base, with the
   recorded head an ancestor of the head, read `git diff <last head> <head>`. On another
   base, as after a restack, read `git range-diff <last base>..<last head> <base>..<head>`:
   every commit it shows as new or changed is in the delta, including ones the new base
   brings into range. Read the code the delta calls, with the lenses it matches. Run
   steps 1 to 3 instead when neither holds, or when range-diff can't see the change:
   - a dropped commit (`<`), whose loss can undo a fix;
   - a merge commit in either range (`git rev-list --merges`), which it leaves out;
   - a binary file in either range (`-` counts in `git diff --numstat`), whose new
     content still shows as unchanged (`=`).
2. **Checks**: the **Verification** lens's checks at the head, a trial merge with the
   base branch's tip (`git merge-tree --write-tree <tip> <head>` exits 0), where the tip
   is `origin/<base branch>` after a fetch, or the parent layer in an unpushed stack, and
   the **PR** lens.
3. **Blockers**: rerun the real run or test that showed each fixed Blocker. A delta
   crossing a boundary the last verdict's real runs didn't cover gets its **Real run**,
   as does each real run that verdict couldn't do.
4. **Earlier findings**: each one the last verdict marked fix is gone at the head, and
   so is every other instance of its class the change caused or made redundant,
   searched across the repo. One still there stays open, under its number.

When the re-check's verdict is ✅ **Done**, with no Blocker or Cleanup open, new or
earlier, and no real run outstanding, say "Nothing further", name the delta checked, and
record Done for the new head. Optional finds go on one folded line, not as
findings: `Also seen (Optional): <a few words each>`, without numbers or cards. Offer one
as a `Next` option only when it carries a real risk, such as a security gap.

**Done when:** the verdict is given and recorded, or a `known` re-check stopped.

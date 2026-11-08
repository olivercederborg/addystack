# Ratchet, replay, and exceptions

How a new check lands in a repo that already has hits, how to prove it, and the one
format for an exception. Each rule here comes from the run on Strict (workout-tracker),
whose checker is `scripts/check-lint-baseline.mjs`.

## The baseline

Existing hits go into the repo's baseline file, counted per rule, so fixing a hit never
fails and adding one does:

- **ESLint**: `eslint --suppress-rule <rule> <paths>` writes
  `eslint-suppressions.json`; `--prune-suppressions` drops fixed ones.
- **oxlint**, or a custom runner: the repo's own baseline file and the script that
  writes it, such as Strict's `node scripts/mica-lint.mjs --suppress-all <paths>`,
  which writes `oxlint-suppressions.json`.

Find which one the repo uses in step 1 and add to it.

## When a baseline may grow

A rule adds baseline entries only on the branch that turns it on. The guard reads the
lint config at the merge base, not at the default branch's head:

```bash
base=$(git merge-base origin/main HEAD)
git show "$base:.oxlintrc.json"    # or eslint.config.js, read through --print-config
```

- A rule the merge base's config turns on may not grow: the branch fixes its new hits.
- A rule only the branch turns on is a rollout, and its first entries are allowed.
- Category rules count as on: resolve each config with the tool's own expansion
  (`oxlint --print-config`, `eslint --print-config <file>`), since a rule enabled through
  a category such as `correctness` slipped past Strict's first checker.

When the repo's guard lacks this rule, so rules with no entries can grow unseen, closing
that gap is its own check in its own commit (Strict's Mica 78, closed in #181). It is the
one check proven by a repro, since a missing guard leaves no failing commit to replay: on
a scratch change, add a baseline entry for a rule the merge base already turns on and
show the new guard fails while the old one accepts it (#181: exit 1 on the new checker,
0 on the old), then show the new guard passes for a true rollout.

## Per occurrence

Under a per-file count, a rule reports each occurrence: each call, cast, or literal. A
rule that reports once per file or per import lets new hits into files that already have
one. Strict's first memo ban flagged the `useCallback` import, so a second `useCallback`
in the same file passed.

## Replay proof

Each check, and each sub-check, fails on a real past mistake. On a clean tree:

```bash
git show <fix>^:<path> > <path>     # the file as it was before the fix
<the repo's lint command> <path>    # fails, naming the rule
git restore <path>
<the repo's lint command> <path>    # passes
```

ESLint can read the old file from stdin instead: `git show <fix>^:<path> | npx eslint
--stdin --stdin-filename <path>`. oxlint has no stdin mode, so put the file back in the
tree. When the fix commit is the first one in the history to touch the file, replay the
introducing commit (`git show <sha>:<path>`) instead.

Show the command and its output for both runs. A sub-check with no past mistake to
replay is removed, not kept "just in case"; the baseline guard above is the exception.

## Exceptions

An exception sits on the offending line, as the tail of the disable comment, in exactly
this format:

```ts
// eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per mount by design, expires 2026-12-31, approved by Sam
// oxlint-disable-next-line mica/no-json-cast -- fixture file read in a test script, expires 2026-11-30, approved by Sam
```

Write one only when the user approves that exception in this session. A baseline entry
for a rule already on at the merge base is the same exception without a reason or an
expiry, so offer the fix or an inline exception instead.

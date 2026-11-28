# Replay: scoping the oxlint migration (T3 367329d6, 2026-11-03 13:52)

Repo: franklin-next. Gated: code changes wait for Oliver's go. You're running a scope-grill
for step 2 of the linting migration: oxlint alongside a slim ESLint. Step 1, oxfmt instead of
Prettier, is merged. Step 3, removing ESLint, waits until oxlint's JS plugins get type info.
Nothing for step 2 is built yet.

## What the research found (oxlint 1.90.0)

- 240 rules are built into oxlint; 222 rules from existing ESLint plugins ran unchanged as
  oxlint JS plugins, including Franklin's 20 untyped rules with identical finding counts.
- 42 can't run correctly yet: the 3 typed Franklin rules, boundaries (0 findings under oxlint
  where ESLint finds 4, since oxlint can't resolve imports), and the 38 `jsonc/*` rules.
- Codex's cross-review (6 points, all hold) kept `prefer-inferred-function-return-type` and
  `eslint-comments` in ESLint, required a built-in rule to match a plugin's finding counts
  before replacing it, and made the lint-baseline gate map renamed rules.

## Decisions so far

- **Round 1** (Oliver): "As much as we can move to oxlint, we should." Every rule oxlint runs
  correctly moves; ESLint keeps the typed promise rules, boundaries and the JSON rules.
- **Round 2**: perfectionist keeps sorting imports as a JS plugin. The 79 `eslint-disable`
  lines naming moved rules "would be reported as unused by ESLint, which no longer runs
  those rules", so they become `oxlint-disable … -- reason`, keeping the reason text. A
  small new Franklin rule would keep the reason required.
- **Round 3** (Oliver): "As much as we can move over to Oxlint and Ox format and keep the setup
  with Ox format and Oxlint lean, it would be the preferred end setup." Oliver took all three
  picks of that round. Converting the 79 comments is part of moving the rules. The rest are
  the **round-3 cleanups**:
  1. oxfmt `sortImports` orders import statements and oxlint's built-in `sort-imports` orders
     names; perfectionist's `sort-named-exports`, `sort-exports` and `sort-jsx-props` go.
     Needs a generated re-sort commit.
  2. oxfmt's `sortPackageJson` takes over `package.json` key order, and the 38 `jsonc/*`
     rules go. ≈25 `package.json` files may be re-sorted.
  3. The new Franklin rule that requires a reason on `oxlint-disable`.
- **Round 4–5**: Oliver: "Let's keep the boundaries rewrite as its own PR, like a follow-up,
  probably the last PR." Open question: drop 13 style-only rules with no oxlint equivalent
  (`@stylistic`, antfu, some jsdoc, `command`), or carry them as oxlint JS plugins.
  Oliver: "Is the easiest just to carry the MSGS plugins for now?" You answered yes: no rules
  dropped, no disable comments become unused, all of them already ran as JS plugins in the
  research, and dropping them later is a config edit.

**Plan size now**: ~5 PRs, ≈180 files, 0 migrations.

## The thread

Oliver: "We want to keep the scope quite minimal just for the migration and then we can clean
up even more later on as follow-ups"

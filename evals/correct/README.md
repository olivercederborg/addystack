# correct evals

Four scenarios over one fixture, built offline by [`setup.sh`](setup.sh) (writes only
under `/tmp`, fixed commit dates so SHAs repeat). Prompts, turns, and assertions are in
[`evals.json`](evals.json); run them with `maintainer/evals.py` as [evals/README](../README.md)
describes.

```sh
./setup.sh   # /tmp/correct-eval, its bare origin, /tmp/correct-eval-exception, /tmp/correct-eval-branch, /tmp/correct-eval-t3.sqlite
```

## The fixture

`/tmp/correct-eval` is a small Expo-style TS repo with a zero-dependency lint
(`npm run lint`, or `node scripts/lint.mjs [paths] | --stdin <path> | --suppress <rule>`):
regex rules, the rules `lint.config.json` turns on, a per-file count ratchet in
`lint-baseline.json`, and `// lint-disable-next-line <rule> -- …` exceptions. CI
(`.github/workflows/ci.yml`) runs the same command, skipping drafts and Markdown-only
changes. `AGENTS.md` has a two-row rule table, one row `none: review`.

Its history replays the Strict run's classes as review-fix commits ("From verify-work:
…"):

| Class | Fix commits | Expected |
|---|---|---|
| A: Effect run to a promise, failure handled with `.catch`, try/catch, `.finally` | 3 | class, lint rule |
| B: manual `useMemo`/`useCallback` under the React Compiler | 2 | class, per-call lint rule |
| C: literal spacing instead of theme tokens | 2 plain commits, after 2 typed T3 corrections | class, lint rule |
| D: `JSON.parse(x) as T` instead of decoding | 1 | skipped, below the bar |

Still in the code, to be baselined: one class-A hit (`src/profile/avatar.ts`), two memo
calls and one literal gap (`src/ui/history-chart.tsx`), the property the exercise-list fix
corrected.

`/tmp/correct-eval-t3.sqlite` holds T3's three tables with the two spacing corrections, a
one-off branch rename, and rows that must be dropped: agent-sent notes (two about named
exports), an assistant reply, a task notification, injected AGENTS.md text, and another
project's message. `"$(python3 maintainer/kit_path.py)/skills/primitive/correct/scripts/corrections.py" --db`, run from the workshop root, reads it.

`/tmp/correct-eval-exception` is the repo after the class-A rule shipped on main (its own
origin), with its AGENTS.md ratchet bullets, on `feature/sync-retry`, which adds one new
class-A hit.

`/tmp/correct-eval-branch` is main as above (its own origin) on `feature/set-notes`, whose
one commit, the agent's current change, adds a new `useCallback` in `src/ui/set-notes.tsx`.
`fix-on-branch` checks that the run builds on that branch, fixes the new call, and
baselines only `src/ui/history-chart.tsx`'s two hits from main.

## Not covered yet

- The devbox route and real `gh` sources (PR comments, CI logs)
- A gated repo, where the plan goes through scope-grill
- A repo with a findings loop, where each rule ships as a proposal
- A repo whose `AGENTS.md` keeps no rule table, where the run should leave it untouched
- `exception-ask` triggering the skill: its prompt matches none of the description's
  branches, so it mostly tests the AGENTS.md rules a past `/correct` run wrote

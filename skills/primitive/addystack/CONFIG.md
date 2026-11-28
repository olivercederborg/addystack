# Configuring addystack

`addystack` below is short for `python3 ~/.agents/skills/addystack/bin/addystack`, or
`python3 ~/.claude/skills/addystack/bin/addystack` after a Claude-only install.

## Files

Your settings live in `~/.config/addystack/`, which you can keep in your dotfiles:

- `addystack.jsonc` is your config. Keys you leave out use the kit's defaults. Its
  `$schema` documents each key, and [`examples/addystack.jsonc`](examples/addystack.jsonc)
  shows them in use.
- `global.md` holds your own global instructions. The build adds them to the kit's only
  when your config sets `"instructions": "global.md"`. `install` sets it when it moves text
  there. If you create the file yourself, set it too.
- `notes/` holds steps you add to core skills.

## Applying an edit

Run `addystack build`. If you changed `hosts`, `hooks`, or `replies`, run
`addystack install` instead, since those decide which hooks are installed.

The build overwrites `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, so keep your own
instructions in the file `instructions` names. `addystack print-config` prints the merged config.

## Policy

`policy.defaults` sets how agents work everywhere, and `policy.repos` rules override it
for checkouts matched by `path` or `remote`. The first value listed is the default:

- `planning`: `gated` waits for your approval of the plan, `autonomous` doesn't.
- `trust`: `draft` stops at draft PRs, `gate` merges once the merge gate allows it, and
  `merge-on-go` merges when you say so.
- `pushVia`: `git`, or `gh-stack` to push through `gh stack`.

A repo can commit `.agents/addystack.jsonc` to make these stricter, never looser. It can
also name the GitHub App that reviews its ready PRs, such as
`"review": { "app": "my-reviewer" }`, so every teammate's agents wait for that App's
approval instead of a person's; your config's own `review`, when set, wins, and a
`policy.repos` rule's `"review": null` turns the repo's App off. To see why an
agent stopped, run `addystack policy --repo <checkout> --explain`.

## Check queue

On macOS, the agent memory guard runs at most `checkQueue.maxChecks` busy heavy checks
(tsc, tsgo, tsgolint, oxlint, eslint, jest, vitest) at once across every agent, and holds
a new one while running checks use `checkQueue.maxCores` cores or more. A held check waits,
stopped, and resumes when a check finishes or goes idle (under 0.1 cores for 30 seconds);
one that still waits after 15 minutes is killed, and the agent is told why. Test runs
(vitest, jest) count but are never held, since a stop fails their timeouts, so they can
pass the cap, and type checks and lints wait behind them. `"checkQueue": { "enabled": false }` turns it off. A change
applies after `addystack build`, without restarting the guard.

## Notes

To add a step to a core skill, write `notes/<skill>.md`, such as `notes/verify-work.md`
containing "Also run `make lint`.", and run `addystack build`. A skill refuses a note that
drops one of its stops or approval gates. To remove a step, install your own skill under
another name.

# addystack

Skills for coding agents in Claude Code and Codex. They plan, build, check, review, and
ship code, and stop where you tell them to. One config file holds your preferences, and
the kit builds your agents' global instructions and hooks from it.

## Install

You need Node.js with npm, Python 3.9 or later, and git.

```sh
npx skills add olivercederborg/addystack -g
python3 ~/.agents/skills/addystack/bin/addystack init
python3 ~/.agents/skills/addystack/bin/addystack install
```

1. `npx skills add` installs every skill. Add `--skill <name>` to install only some.
2. `init` writes your config from what it detects, such as the agents on your PATH.
3. `install` adds the kit's hooks beside yours and moves any text you wrote in
   `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md` into `~/.config/addystack/global.md`.
   Then it builds and runs `doctor`.

Run `addystack doctor` any time to check the install. It names the fix for each problem.
In an agent session, `/addystack` does all of this for you.

## Skills

A skill calls only skills in its own layer or a lower one. Each skill's `SKILL.md`, in
`skills/<layer>/<skill>/`, says when to use it.

| Layer | Skills |
|---|---|
| primitive: one job each | `scope-grill`, `architect`, `build`, `review-loop`, `verify-work`, `open-pr`, `address-review`, `review-teammate-pr`, `grounding`, `tidy`, `blast-radius`, `show-me-your-work`, `orchestrate`, `unslop`, `correct`, `reflect`, `addystack` |
| orchestrator: runs primitives as steps | `autopilot` builds an approved plan to a verified PR stack, `babysit` keeps a watched PR moving, `coordinator` runs a project from one thread |
| optional: not core, so `update` never adds or removes them | `reply-shape`, `review-artifact`, `use-lakebed`, `ketchup`, `bro`, `in-your-own-words` |

## Config

Your settings live in `~/.config/addystack/`, which you can keep in your dotfiles:

- `addystack.jsonc` is your config. Keys you leave out use the kit's defaults. Its
  `$schema` documents each key, and
  [`examples/addystack.jsonc`](skills/primitive/addystack/examples/addystack.jsonc) shows
  them in use.
- `global.md` holds your own global instructions. The build adds them to the kit's.
- `notes/` holds steps you add to core skills.

After an edit, run `addystack build`, or `addystack install` if you changed `hosts`,
`hooks`, or `replies`. The build overwrites `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`,
so keep your own instructions in `global.md`. `addystack print-config` prints the merged
config.

`policy.defaults` sets how agents work everywhere, and `policy.repos` rules override it
for checkouts matched by `path` or `remote`. The first value listed is the default:

- `planning`: `gated` waits for your approval of the plan, `autonomous` doesn't.
- `trust`: `draft` stops at draft PRs, `gate` merges once the merge gate allows it, and
  `merge-on-go` merges when you say so.
- `pushVia`: `git`, or `gh-stack` to push through `gh stack`.

A repo can commit `.agents/addystack.jsonc` to make these stricter, never looser. To see
why an agent stopped, run `addystack policy --repo <checkout> --explain`.

To add a step to a core skill, write `notes/<skill>.md`, such as `notes/verify-work.md`
containing "Also run `make lint`.", and run `addystack build`. A skill refuses a note that
drops one of its stops or approval gates. To remove a step, install your own skill under
another name.

## Update

```sh
python3 ~/.agents/skills/addystack/bin/addystack update
```

This updates the skills, adds skills that became core, removes core skills the release
dropped, and runs `install` again. `/addystack update` also summarizes
[`CHANGELOG.md`](CHANGELOG.md) and flags notes whose skill changed.

## Working on the kit

Once per clone:

```sh
git config core.hooksPath .githooks
```

The pre-commit hook runs the lints and tests, through `dagger check` when Dagger can reach
an engine. `dagger check -l` lists the checks.

Shared files are copied into the skills that use them, because the skills CLI skips
symlinks. Edit the source listed in [`scripts/copies.txt`](scripts/copies.txt), then run
`scripts/sync-copies.py`.

## Credits

A skill that adapts or copies an MIT skill carries its license in a `NOTICE` file.

- [Matt Pocock's skills](https://github.com/mattpocock/skills): `scope-grill` adapts `grilling`, `reflect` adds checks from `retro`, and the kit uses `codebase-design`, `domain-modeling`, `tdd`, and `diagnosing-bugs` when installed.
- [Lauren Tan's pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT): the source of `reflect`, `correct`, `architect`, `ketchup`, `blast-radius`, `show-me-your-work`, `unslop`, `bro`, `in-your-own-words`, and the rules in `autopilot` and `orchestrate`.
- [Ben Holmes's skills](https://github.com/bholmesdev/skills) (MIT): `tidy` adapts `simplify`.
- [Ayoub Ghriss's i-have-adhd](https://github.com/ayghri/i-have-adhd) (MIT): `reply-shape` adapts it.
- [HumanLayer's skills](https://github.com/humanlayer/skills): `open-pr`'s default body follows `visual-pr`.
- `use-lakebed` started in a team's skill registry and pins Lakebed 0.0.41.

## License

MIT. See [`LICENSE`](LICENSE).

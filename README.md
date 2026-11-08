# addystack

Skills for coding agents in Claude Code and Codex. They plan, build, check, review, and
ship code, and stop where you tell them to. One config file holds your preferences, and
the kit builds your agents' global instructions and hooks from it.

## Install

You need Node.js 22.20 or later with npm, Python 3.9 or later, and git.

```sh
npx skills add olivercederborg/addystack -g
python3 ~/.agents/skills/addystack/bin/addystack init
python3 ~/.agents/skills/addystack/bin/addystack install
```

1. `npx skills add` installs the skills. To install only some, pass `--skill <names>`
   and keep `addystack`, whose tool the next steps run.
2. `init` writes your config, including the agents it finds on your PATH. Run it first:
   `install` works only on those agents.
3. `install` adds the kit's hooks beside yours and moves text you wrote in
   `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md` into `~/.config/addystack/global.md`,
   where your own instructions live from now on. Then it builds and runs `doctor`.

After a Claude-only install, the tool is in `~/.claude/skills/addystack/` by default, so
use that path in place of `~/.agents/skills/addystack/` in every command here. Below,
`addystack` is short for `python3 ~/.agents/skills/addystack/bin/addystack`.

Run `addystack doctor` any time to check the install. It names the fix for each problem.
In an agent session, `/addystack` does all of this for you.

## Skills

A skill calls only skills in its own layer or a lower one. Each skill's `SKILL.md`, in
`skills/<layer>/<skill>/`, says when to use it.

| Layer | Skills |
|---|---|
| primitive: one job each | `scope-grill`, `architect`, `build`, `review-loop`, `verify-work`, `open-pr`, `address-review`, `review-teammate-pr`, `grounding`, `tidy`, `blast-radius`, `show-me-your-work`, `orchestrate`, `unslop`, `correct`, `reflect`, `addystack` |
| orchestrator: runs primitives as steps | `autopilot` builds an approved plan to a verified PR stack, `babysit` keeps a watched PR moving, `coordinator` runs a project from one thread |
| optional: extras `update` never adds or removes | `reply-shape`, `review-artifact`, `use-lakebed`, `ketchup`, `bro`, `in-your-own-words` |

## Config

Your settings live in `~/.config/addystack/addystack.jsonc`.
[`CONFIG.md`](skills/primitive/addystack/CONFIG.md) covers the files there, which command
applies an edit, policy, and notes.

## Update

```sh
python3 ~/.agents/skills/addystack/bin/addystack update
```

It updates the skills, adds skills that became core, removes core skills it dropped, and
reruns `install`. `/addystack update` also summarizes [`CHANGELOG.md`](CHANGELOG.md) and
flags notes whose skill changed.

## Working on the kit

Once per clone:

```sh
git config core.hooksPath .githooks
```

The pre-commit hook runs the lints and tests, through Dagger when it can reach an engine
(`dagger check -l` lists them).

Shared files are copied into the skills that use them, because the skills CLI skips
symlinks. Edit the source listed in [`scripts/copies.txt`](scripts/copies.txt), then run
`scripts/sync-copies.py`.

## Credits

- [Matt Pocock's skills](https://github.com/mattpocock/skills): `scope-grill` adapts `grilling`, `reflect` adds checks from `retro`, and the kit uses `codebase-design`, `domain-modeling`, `tdd`, and `diagnosing-bugs` when installed.
- [Lauren Tan's pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT): `reflect`, `correct`, `architect`, `ketchup`, `blast-radius`, `show-me-your-work`, `unslop`, `bro`, and `in-your-own-words` come from it (see each one's `NOTICE`), and `autopilot` and `orchestrate` take rules from its playbooks.
- [Ben Holmes's skills](https://github.com/bholmesdev/skills) (MIT, see its `NOTICE`): `tidy` adapts `simplify`.
- [Ayoub Ghriss's i-have-adhd](https://github.com/ayghri/i-have-adhd) (MIT, see its `NOTICE`): `reply-shape` adapts it.
- [HumanLayer's skills](https://github.com/humanlayer/skills): `open-pr`'s default body follows `visual-pr`.
- `use-lakebed` started in a team's skill registry and pins Lakebed 0.0.41.

## License

MIT. See [`LICENSE`](LICENSE).

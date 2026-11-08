# addystack

addystack is a kit of skills for coding agents in Claude Code and Codex. The skills plan,
build, check, review, and ship code, and stop where you say. You keep your own
preferences in one config file, and the kit builds your agents' global instructions and
hooks from it.

## Install

You need Node.js with npm, Python 3.9 or later, and git. Install the skills, then the
tool that comes with them:

```sh
npx skills add olivercederborg/addystack -g
python3 ~/.agents/skills/addystack/bin/addystack install
python3 ~/.agents/skills/addystack/bin/addystack init
python3 ~/.agents/skills/addystack/bin/addystack build
```

- `npx skills add` copies every skill into `~/.agents/skills/` and links each agent's
  skill folder to it. Add `--skill <name>` to install only some.
- `addystack install` merges the kit's hooks into `~/.claude/settings.json` and
  `~/.codex/hooks.json` and keeps every hook you already had. The first time, it moves
  your existing `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` into
  `~/.config/addystack/global.md`, so nothing you wrote is lost. Then it builds and runs
  `doctor`.
- `addystack init` writes `~/.config/addystack/addystack.jsonc` from what it detects: your
  name from git, which agents are on your PATH, and the `global.md` install made.
- `addystack build` applies the config. After you change its `hooks` or `replies`, run
  `addystack install` again instead, which merges the hooks and builds.

`addystack doctor` checks the whole install and names the fix for anything wrong. In an
agent session, `/addystack` does all of this for you: it looks things up, asks only
what's left, and shows each change before it writes.

## The skills

The skills sit in layers, and a skill only calls skills in its own layer or a lower one.

- **primitive** skills do one job each: `scope-grill`, `architect`, `build`,
  `review-loop`, `verify-work`, `open-pr`, `address-review`, `review-teammate-pr`,
  `grounding`, `tidy`, `blast-radius`, `show-me-your-work`, `orchestrate`, `unslop`,
  `correct`, `reflect`, and `addystack`.
- **orchestrator** skills run primitives as their steps: `autopilot` builds an approved
  plan to a verified stack of PRs, `babysit` keeps a watched PR moving, and
  `coordinator` runs a project from one thread.
- **optional** skills are off until you use them: `reply-shape`, `review-artifact`,
  `use-lakebed`, `ketchup`, `bro`, and `in-your-own-words`.

Each skill's `SKILL.md`, under `skills/<layer>/<skill>/`, says when to use it.

## Your config

Your settings live in `~/.config/addystack/`, a folder you can keep in your dotfiles:

- `addystack.jsonc` is your config. Each key you leave out falls back to the kit's
  defaults. Its `$schema` documents every key, and
  [`examples/addystack.jsonc`](skills/primitive/addystack/examples/addystack.jsonc)
  shows them in use.
- `global.md` holds your own global instructions. The build adds them to the kit's.
- `notes/` holds your notes on core skills (see below).

Run `addystack build` after each edit, or `addystack install` when it changes `hooks` or
`replies`. The build writes `~/.claude/CLAUDE.md`,
`~/.codex/AGENTS.md`, and a resolved copy of your config that the hooks read.
`addystack print-config` shows the merged result.

## Policy

`policy` sets how agents work in each checkout:

- `planning`: `gated` waits for your approval of the plan; `autonomous` writes its own
  brief from your request.
- `trust`: how far agents go on their own. `draft` stops at draft PRs, `gate` marks PRs
  ready and merges once every check passes, and `merge-on-go` merges when you say so.
- `pushVia`: how branches reach GitHub, such as through `gh stack`.

`policy.defaults` applies everywhere, and each rule in `policy.repos` applies to the
checkouts it matches, by path or remote. A repo can also commit
`.agents/addystack.jsonc` with its own `planning`, `trust`, and `pushVia`. Each of those
takes the stricter of the repo's value and yours, so a repo can make agents more careful,
never less. To see why an agent stopped, run
`addystack policy --repo <checkout> --explain`.

## Notes

A note adds steps to a core skill without copying it. Write
`~/.config/addystack/notes/<skill>.md`, such as `notes/verify-work.md` with
"Also run `make lint`.", and run `addystack build`. The skill reads its note at the start
and names it in its reply. A note can only add steps: a skill refuses a note that drops
one of its stops or approval gates. To drop a step, install your own skill under another
name instead.

## Update

```sh
python3 ~/.agents/skills/addystack/bin/addystack update
```

It updates the installed skills, adds the skills a release makes core, removes the ones
it dropped, and runs `install` again. `/addystack update` also summarizes what changed in
[`CHANGELOG.md`](CHANGELOG.md) and flags notes whose skill changed.

## Working on the kit

Run `git config core.hooksPath .githooks` once per clone. The pre-commit hook runs the
lints and the test suites, as `dagger check` when Dagger can reach an engine.
`dagger check -l` lists the checks. Shared files are copied into each skill that needs
them, since the skills CLI skips symlinks: edit the source named in
[`scripts/copies.txt`](scripts/copies.txt), then run `scripts/sync-copies.py`.

## Credits

- **Matt Pocock's skills** ([mattpocock/skills](https://github.com/mattpocock/skills)):
  - `scope-grill` adapts the design-tree rounds from `grilling`.
  - addystack uses `codebase-design`, `domain-modeling`, `tdd`, and `diagnosing-bugs` when
    they're installed. The one-line rules it needs from them are copied in, so it
    works without them.
- **Lauren Tan's pstack** ([cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack),
  MIT; see each skill's `NOTICE`):
  - `reflect`, `correct`, `architect`, `ketchup`, `blast-radius`, `show-me-your-work`, and
    `unslop` are adapted from pstack's skills of the same names. `reflect` adds
    environment checks from `retro` in Matt Pocock's skills.
  - `bro` and `in-your-own-words` are pstack's skills, unchanged.
  - `autopilot` takes its rules from pstack's `autopilot-stack` playbook, and
    `orchestrate` its brief fields and child-task rules from the `orchestrate` playbook.
- **`tidy`** is adapted from Ben Holmes's `simplify`
  ([bholmesdev/skills](https://github.com/bholmesdev/skills), MIT; see its `NOTICE`).
- **`reply-shape`** is adapted from Ayoub Ghriss's `i-have-adhd`
  ([ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd), MIT; see its `NOTICE`).
- **`open-pr`**'s default body is modeled on HumanLayer's `visual-pr`
  ([humanlayer/skills](https://github.com/humanlayer/skills)).
- **`use-lakebed`** started in a team's skill registry. This copy pins Lakebed 0.0.41.

## License

MIT. See [`LICENSE`](LICENSE).

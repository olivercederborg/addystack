# Changelog

Each release, newest first. `/addystack update` summarizes the entries above the version
you had.

## Unreleased

- **Check queue** (macOS, in the agent memory guard): at most `checkQueue.maxChecks` (4)
  heavy checks, such as tsc, eslint, oxlint, and vitest, run at once across every Claude
  and Codex agent, and a new one also waits while running checks use
  `checkQueue.maxCores` (10) cores or more. A waiting check is stopped at its start and
  resumed oldest first; one still waiting after 15 minutes is killed, and the agent is
  told why. A check idle for 30 seconds stops counting, so a watcher can't hold a slot.
  Agents also get a note before a Bash call while checks wait.
  `"checkQueue": { "enabled": false }` turns it off. The note and Codex's notice are new
  hook entries: in a git checkout you pull yourself, run `addystack install` to add them;
  `addystack update` does it for you.

## v0.1.0

The first release.

- **Skills**, in three layers. Primitive: `scope-grill`, `architect`, `build`,
  `review-loop`, `verify-work`, `open-pr`, `address-review`, `review-teammate-pr`,
  `grounding`, `tidy`, `blast-radius`, `show-me-your-work`, `orchestrate`, `unslop`,
  `correct`, `reflect`, and `addystack`. Orchestrator: `autopilot`, `babysit`, and
  `coordinator`. Optional: `reply-shape`, `review-artifact`, `use-lakebed`, `ketchup`,
  `bro`, and `in-your-own-words`.
- **The `addystack` tool**, inside the `addystack` skill: `install`, `update`, `init`,
  `build`, `doctor`, `print-config`, and `policy`.
- **One config**, `~/.config/addystack/addystack.jsonc`, checked against
  `schema/v1.json`, over the kit's defaults.
- **Policy per checkout**: `planning`, `trust`, and `pushVia`, set by your defaults and
  `policy.repos` rules, and made stricter by a repo's own `.agents/addystack.jsonc`.
  `policy --explain` shows which rule set each field.
- **Notes**: `~/.config/addystack/notes/<skill>.md` adds steps to a core skill.
- **Hooks**, picked by tag and by your reply settings, merged into Claude Code's and
  Codex's settings beside your own.
- **The `/addystack` skill**: set up, change a setting, add a note, explain a stop,
  update, or send a kit change upstream.
- **`turn_block.py`** (`hooks/turn_block.py`) is a public module: code outside the kit
  can import it through `resolved.kit()`, and it changes only under semver.

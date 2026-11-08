# Note

A note adds steps to one core skill without copying it. The user writes it in
`notes/<skill>.md` beside the config (`~/.config/addystack/notes/`), and
`addystack build` copies it to `~/.local/state/addystack/notes/<skill>.md`, where the
skill's **Notes** line reads it.

## 1. Look up

- **The skill.** It must be core: its layer in `<kit>/core/skills.json` is `primitive`
  or `orchestrator`. A note for any other skill isn't built. For an optional or personal
  skill, the user edits that skill itself.
- **The existing note**, if `notes/<skill>.md` is there. Add to it; one file per skill.
- **Where the step fits.** Read the skill's `SKILL.md`, and name the step the note runs
  before or after, so the note says "Before the verdict, …", never "Instead of …".

## 2. Check it adds

A note adds steps. Refuse one that removes, skips, or loosens any of these, and say which
line it would drop:

- a Stop or approval gate, such as waiting for the user's go, or a merge gate;
- a recorded verdict, check, or review the skill runs;
- a Done when the skill sets.

To drop a step, the user doesn't install that skill and writes their own under another
name. Offer that instead.

## 3. Preview

Show `diff -u` of the note (or `/dev/null`) and the proposed note: a few bullets, each
one step, in the imperative, naming its anchor step.

## 4. Write

On the user's okay, write `notes/<skill>.md`, run `<kit>/bin/addystack build`, and check
the built copy exists. Run `<kit>/bin/addystack doctor`: its `notes` check names a note
whose skill isn't core.

**Done when:** the built note exists under the state folder's `notes/`, and `doctor`'s
`notes` check passes.

# Evals

## How we improve a skill

Each skill's evals live in `evals/<skill>/`. A scenario in an `evals.json` that sets a
`cwd` runs through `maintainer/evals.py`, from the repo root; the rest, such as
`scope-grill/`'s README rubric, run by hand as their README says.

```sh
maintainer/evals.py list [skill]                     # scenarios, turns, assertions
maintainer/evals.py start <skill> <id> OUT [--variant DIR]
maintainer/evals.py turns <skill> <id>
maintainer/evals.py replies <skill> <id> OUT
maintainer/evals.py grade-brief <skill> <id> --replies OUT/<skill>/<id>.replies.md
maintainer/evals.py record OUT <skill> <id> GRADES
maintainer/evals.py table SIDE --against BEFORE_SIDE
```

[Run with the runner](#run-with-the-runner) says who plays and who grades each step.

The loop:

1. **Find a weak spot in real threads**: a correction you keep making, a review miss,
   a slow step. The `correct` skill mines your corrections.
2. **Write or extend a scenario** that fails the way the thread did.
3. **Set the bar before any run**: which assertions must flip, and that no control
   regresses.
4. **Replay before and after**, each side its own folder of trials, as in
   [A/B a change](#ab-a-change). Name the sides `X` and `Y`, since the grader sees the
   replies' path, so it grades blind.
5. **Ship only on a win.** A pure speed or friction change, or a cut, ships on a tie.
6. **Run `verify-work` and `review-loop`** on the PR before it merges.

Each skill's folder holds scenario evals for that skill. Grade each assertion PASS or
FAIL in a fresh session, and quote the evidence.

**Mode.** The skill evals assume no autonomy, which is how a skill behaves when
installed on its own. Once the router (the kit's `core/router.md`) is active, start
each of those sessions with "no autonomy this session". The router's own flows are tested in
[`router/`](router/). The autopilot `two-layer` scenario runs with the router's autonomy,
as Oliver's own sessions do, so its brief has no "no autonomy" line.

## Run with the runner

Scenarios in an `evals.json` run through `maintainer/evals.py`; `list` shows them. A
scenario runs only when it sets `cwd` (where the player works), and usually `setup` (a
shell command run from its folder that builds `cwd`) and `preamble` (text the player
gets before the prompt), as [reply-shape's](reply-shape/evals.json) do. A scenario that sets `"tool_calls": true` also gets every tool call the player and its native subagents made, with each result, in its saved replies, for assertions about what ran rather than what the reply says. A relative
`cwd` resolves inside each trial's own folder, and `{cwd}` in `setup` becomes that
path, so trials of one scenario can run at once, as
[autopilot's](autopilot/evals.json) do. Players must be T3 child tasks, since native
subagents skip SessionStart hooks. Each brief opens with
`Reply rules: on`, since the reply-rules hook skips T3 child tasks without that line,
and players must get the rules as Oliver's own sessions do.

Each trial writes to its own folder, `OUT`. A side is a folder of trials, such as
`/tmp/skill-evals/<change>/X/t1` and `X/t2`. Run 2 trials a side when the
player's path varies from run to run, as autopilot's does; one is enough for a short
scenario. For each scenario in a trial:

1. Run `evals.py start <skill> <id> OUT`, with a `--variant <dir>` for each skill the
   side reads from a folder. It runs the setup, writes `OUT/<skill>/<id>/trial.json`,
   and prints the brief.
2. Start the player with `delegate_task`: `target: {driverKind: "claudeAgent", model:
   "claude-opus-5-5", options: {effort: "medium"}}`, `role: "test"`, `mode: "wait"`,
   `timeoutMs: 1800000`, `clientRequestId: "eval-<change>-<side>-<trial>-<skill>-<id>"`,
   and the printed brief as `task`.
3. Send each turn from `evals.py turns` to the same child, with `t3_thread_send` to the
   returned `childThreadId`, not a new `delegate_task`. Wait with `t3_thread_wait`.
4. Run `evals.py replies <skill> <id> OUT` once the player finishes. It finds the
   transcript whose first message is the trial's brief, saves the replies, and writes
   `OUT/<skill>/<id>/cost.json`. Each trial's brief names its own cwd, so parallel
   trials can't pick each other's transcript.
5. Grade with a fresh `delegate_task` on Codex: `target: {driverKind: "codex", model:
   <the model in ~/.codex/config.toml>, options: {reasoningEffort: "high"}}`, `role:
   "test"`, and the output of `evals.py grade-brief <skill> <id> --replies OUT/<skill>/<id>.replies.md`
   as `task`.
6. Save the grader's output as `OUT/<skill>/<id>.grades.txt`, then run
   `evals.py record OUT <skill> <id> <file>` on it.

Then `evals.py table SIDE` prints the pass table, and exits 1 when a trial lacks a
result another trial on the side graded, or a scenario it began.

## A/B a change

A change to a skill or to the reply rules runs three arms, each its own side, on every
scenario that exercises the changed text, with the same trials on each:

- **current**: the base's text.
- **new**: the change.
- **none**: the text gone: the cut lines deleted, or the skill's body or the rules empty.

Give each arm its text the same way, so each pays the same cost to read it: a
`--variant` copy for a skill, and for the reply rules `--rules DIR`, a folder holding
`replies.md` and `reply-shape/SKILL.md` that the player reads in place of the installed
ones (`--rules none` drops them). Then run `evals.py table NEW --against CURRENT` and
`evals.py table NONE --against CURRENT` with the folders' full paths. Ship the new text
only when it beats current, or ties it for a pure speed or friction change or a cut.
When none ties too, the text changes nothing, so cut it. The PR body gives each arm's passes with its trial count, and the words before and
after.

With one trial a side, cells show ✅ or ❌.
With more, each shows how many trials passed, and a **flip** is an assertion every
before trial passed and some after trial didn't. Every trial on both sides must grade
the same scenarios, so a trial that lacks one shows it as missing on its side. It exits
1 on a flip or a missing result. A folder that holds results directly counts as a side of one trial.

The table also shows each side's median cost over its trials: wall time, tokens by
kind, and USD. Cost covers the player, its native subagents, and every T3 child below
it, priced at T3's list rates in `~/.t3/userdata/usage-model-rates.json`. The table
warns on a run with no `cost.json`, and shows `?` for USD when a model has no rate.

Limit: cost misses Codex's long-context rates above 272k tokens, compaction calls a
transcript doesn't record, and T3's own calls, such as thread titles. A Codex session
continued in a second rollout file, after an edited message, counts per file, so its
tokens may count twice; no session here has shown one yet. Its USD is list price, not
what a subscription pays.

Limit: `--variant` approximates an installed skill. The player reads the variant, but
the installed skill's description still triggers. The brief tells the player to copy
its variant lines into each child's brief; a child it doesn't copy them to runs the
installed skill.

Limit: `--rules` has the player read the rules, where Oliver's sessions get them from a
SessionStart hook.

Limit: T3 prefixes each player's first message with "Act as the test sub-agent for this
task.", so the player knows it's a child task.

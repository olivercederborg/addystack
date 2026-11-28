# reply-shape evals

Grade the shape of three replies that other evals already produce: turn 1 of
[verify-work](../verify-work/README.md), the `sync/` scenario of
[open-pr](../open-pr/README.md), and turn 2 of [scope-grill](../scope-grill/README.md),
plus a decision card, a merge go for a two-PR stack (`setup-ship-gate.sh`), and four questions whose answers each fit a different view: a
table, a flow, none, and two views for two points. Three more replay explanations from
/bro's "before" replies (`fixtures/`): a report re-explained, a which-question, and a
how-it-works trace. Three read a state file and report it: what happened since the reader left
(`since-you-left`), a project's state (`project-view`), and finished work (`what-changed`).

Each scenario grades the reader's needs (`Reader ·`: could they act without asking "what is
X?", is there a bold line per item to scan, is each item's content grouped under it with
findings by severity, is it brief, and a decision's structure) and the contracts machines
read (`Contract ·`: headline marker, the closing and Next options, the turn block, and a
merge option's plain text), plus its own checks. These came from Oliver's blind picks on
real replies (Nov 10, 2026): a short headline, then a bold line per item, grouped by the thing.

The setup, prompts, and assertions live in [`evals.json`](evals.json). Run them with
the runner in [evals](../README.md#run-with-the-runner).

Open one graded reply in T3 Code and check that the rule above `Next` renders as a
line, not as a heading on the line before it.

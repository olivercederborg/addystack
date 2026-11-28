# ketchup evals

One catch-up with more calls than reply-shape's five-item cap: six PRs waiting on one
merge call, and a header choice whose two options have screenshots. It checks that the
catch-up shows every call and embeds the screenshots inline.

The setup, prompt, and assertions live in [`evals.json`](evals.json). Run them with the
runner in [evals](../README.md#run-with-the-runner). For a change to both `ketchup` and
`reply-shape`, the after run's brief also needs a line pointing at the changed
`reply-shape/SKILL.md`, since `--variant` swaps only the scenario's skill.

Limit: on its first run (Oct 20, 2026, one run each on Opus 5.5 at medium), main's
ketchup and reply-shape passed all seven assertions too, so the scenario guards the
catch-up rule against regressions but hasn't yet shown the old version failing.

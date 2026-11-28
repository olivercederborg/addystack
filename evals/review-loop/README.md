# review-loop evals

This eval reuses the verify-work scenario: `../verify-work/setup.sh /tmp/review-loop-eval`.
Start a fresh Claude Code session in T3 Code in that directory, with Codex enabled as a T3
provider. Send these two turns in order:

1. "have claude and codex review this branch"
2. "a"

Grade each assertion PASS or FAIL, and quote the evidence:

- Both reviewers run: Claude on `claude-opus-5-5` with high effort, and Codex on
  `gpt-6.1-terra` with max reasoning effort, as a T3 child task (`delegate_task`), never
  `codex exec`. A reviewer that fails is labeled as such.
- Round 1 finds the missing `currency` column (Blocker) and the unrequested JSON option. It
  names which reviewer raised each finding.
- Every finding is checked against the code before it is shown. Any finding that
  doesn't hold is dropped, and the drop is stated.
- The verdict is a 🔴 headline naming the blockers. Findings follow as one line each,
  worst first, at most three visible, and checks and evidence sit in the one fold.
- After "a", the fixes, round 2, and any further rounds run without another approval.
  Round 2 has only the Codex reviewer verify each fix. It reports only what is new or
  still open, and ends **Clean** when no blockers or cleanups remain.
- The prompt, packet, and output files are deleted when the loop ends.

# Encode lessons in structure

**Apply when** the user corrects the same thing a second time, or you're about to add a
rule to a skill, `AGENTS.md`, or `CLAUDE.md`.

A lesson that structure can enforce goes there, and the prose it replaces is deleted.
A lesson about the work goes in the skill's source, not in memory.

**Why:** "as long as these rules can be enforced through lint rules, then i like it" ·
"it doesnt belong in the memory - it belongs in the skill source".

**Pattern:**
- **Strongest rung first**: architecture that removes the wrong path (one owner per
  piece of state, one way per task, internals that can't be imported), then a type,
  then a lint whose error names the fix and fails only on new violations, then a hook
  or script, then a test, then prose.
- **Prove it bites**: run the new check on a real past mistake.
- **Only real lessons**: skip a mechanism for what agents already get right: "arent
  agents so good by now that they will find out that the repo is using bun".

**Tell:** the same instruction written twice, or a new rule with nothing deleted.

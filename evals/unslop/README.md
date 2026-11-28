# unslop evals

The cases unslop kept in its own `evals/` folder until the kit stopped installing them, so
an agent using the skill never reads them mid-task. Run them by hand when revising
`unslop`; they have no `evals.json` for the runner yet.

## Evaluate revisions

Check behavior using [cases.md](cases.md), especially preserving technical terms, specifications, structured records, and already-good prose. Match the check to the change. A small wording edit needs a focused review; changes to scope or editorial judgment warrant trying all eight cases.

Use the Meaning, Specificity, Voice, and Restraint rubric. Revise any instruction that changes facts, invents evidence or personality, or damages valid terminology and formatting. Do not require different wording when the input is already good.

When a behavioral comparison would resolve uncertainty, generate outputs with and without the candidate skill using the same model, request, and settings. Judge them in shuffled order without identifying the candidate. Add non-sensitive real examples when available. Prefer a narrow correction over new rules for individual examples.

Keep evaluation outputs and notes in a temporary artifact. State whether the check was a manual review or an independent comparison, and record any checks not completed. Do not claim measured improvement from inspection alone.

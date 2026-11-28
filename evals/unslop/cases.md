# Unslop evaluation cases

Use these cases to compare the same model with and without the skill. Judge behavior, not exact wording.

Score each case from 0 to 2 on four axes:

- Meaning. Facts, uncertainty, scope, and intent survive.
- Specificity. The result uses concrete facts, mechanisms, instructions, or numbers.
- Voice. The result fits the audience without stock AI phrasing or sterile churn.
- Restraint. The edit keeps valid terms and leaves good text alone.

A promotion candidate must score at least 7 of 8 on every case and must not score 0 on Meaning.

## Case 1. Chatbot praise and filler

Input:

> Great question! You're absolutely right that this is a pivotal moment. In order to move forward, it is important to note that we should carefully evaluate the evolving landscape. I hope this helps!

Expected behavior:

- Lead with the actual recommendation.
- Remove praise, puffery, filler, and the stock closing.
- Do not invent the missing recommendation. State that the source text contains none.

## Case 2. Vague evidence

Input:

> Industry experts believe the cache significantly improves performance, ensuring a smoother experience.

Expected behavior:

- Do not convert the claim into a fact.
- Ask for or name the source and measurement when available.
- If no evidence exists, state that the performance claim is unsupported.

## Case 3. Valid technical terms

Input:

> This API surface exposes one primitive for cancellation. The compiler lowers that primitive before code generation.

Expected behavior:

- Keep `API surface` and `primitive` because they carry specific technical meanings.
- Make no change unless surrounding context shows a clearer established term.

## Case 4. Formal specification

Input:

> The worker MUST retry an idempotent request at most three times. It MUST NOT retry a request after a 401 response.

Expected behavior:

- Preserve normative keywords and exact limits.
- Do not add voice, opinion, or rhetorical variation.

## Case 5. Dense documentation

Input:

> The loader, which starts after configuration is parsed and after every plugin has registered its hooks, reads the manifest, validates it, resolves each dependency, and then, when all of those operations have completed successfully, publishes the registry to workers that may already be waiting.

Expected behavior:

- Split the sequence into readable steps or sentences.
- Preserve ordering and the condition for publication.
- Do not add new concurrency guarantees.

## Case 6. Structured log

Input:

> 2026-08-19T12:00:00Z\tverify\tkept retry limit at 3\tproduction p99 stayed below 400 ms\ttrace/42.json\tverified

Expected behavior:

- Leave the record structure intact.
- Do not add human voice.
- Change a cell only if it is unclear or unsupported.

## Case 7. Good human prose

Input:

> I would keep the old parser for one more release. The replacement is faster, but it still gives worse errors for malformed input.

Expected behavior:

- Keep the opinion, contrast, and rhythm.
- Make no change unless evidence or audience requires one.

## Case 8. Promotional copy with real data

Input:

> Our groundbreaking new queue delivers a breathtaking developer experience, processing 12,400 jobs per second in the published benchmark.

Expected behavior:

- Remove promotional adjectives.
- Keep the measured result and its source qualification.
- Do not imply that the benchmark represents production performance.

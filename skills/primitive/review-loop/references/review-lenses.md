<!-- Copy of shared/review-lenses.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Review lenses

Review the change through three lenses, and keep each finding with a concrete
consequence.

- **Spec**: missing, partial, wrong, or unrequested behavior against the linked issue
  and the user's plan or stated intent. Check each claim the change makes, in its PR
  description, docs, comments, or the issue, against the code and the evidence behind
  it.
- **Standards**: the repo's documented conventions for the areas the change touches,
  unclear names, speculative abstraction, middle-man wrappers, and tests that can't
  fail, such as one that reads back what its fake returned. For each new helper, wait,
  type, or flow, search outside the diff for code that already does it, and name the
  duplicate. Leave what tooling enforces to the tooling, but run it: for a manifest or
  config change, run every suite uncached at base and head and compare, skipping and
  naming any that writes shared data or loads secrets. Rerun each new test that awaits
  a mocked async call with that mock delayed.
- **Behavior**: trace each changed path end to end with the real inputs it will meet:
  the entrypoint, validation, authorization and tenancy, data writes, external calls
  and what they cost, retries and idempotency, and the response or rendered UI. Take
  each outside input from its source, not the PR's fixtures: the provider's contract
  or generated client, the platform's event types, a recorded payload. Run the values
  the source allows that the change rejects or assumes away: absent, null, empty, or
  not yet set. Then trace a second run: a retry, a repeat visit, or the next request.
  When a finding sits in a shared helper, list every caller and check each one.

# verify-work evals

Seventeen scenarios, with their setup, prompts, and assertions in [`evals.json`](evals.json).
Run them with the runner in [evals](../README.md#run-with-the-runner).

- **csv-export**: `./setup.sh` builds a repo on `feature/csv-export` with planted
  problems: a missing `currency` column and the test that locks in the wrong header, an
  unrequested `format: "json"` option, a `prepareRows` pass-through with a narrating
  comment, an explicit `: string` return type, an `Array.isArray` guard, and a
  mock-only test. Three turns: review, "fix all", then a push for more.
- **real-run**: `./setup-real-run.sh` builds a repo on `feature/reuse-client`. The
  catalog caches a client that each request closes, the tests' fake client ignores
  `close`, and the server (`bun src/server.ts`, port 4310) fails on its second request.
- **errors**: `./setup-errors.sh` builds a repo on `feature/export-history` whose
  tests pass with fakes that never throw. `runExport` wraps `history.save` in a `catch`
  that only says `// history is best-effort`, so a failed save returns the CSV as if
  saved: a Blocker, since the issue asks for the save. `listRuns` returns `[]` when the
  history read throws, so the page says "No export runs yet." instead of an error: also
  a Blocker, since wrong behavior is one. The row loader's `.catch` logs with context and
  rethrows, and isn't a finding.
- **quick-recheck**: `./setup-quick-recheck.sh` builds csv-export, tags its head
  `verdict-1`, records the Not done verdict with its five findings there, then commits
  fixes. The prompt names no verdict, so the verifier has to find it. The currency fix puts `currency` before `amount` in
  the rows while the header lists `amount,currency`, and its test locks that order in.
  `prepareRows`, marked fix, is still there.
- **recheck-unfixed** and **recheck-not-verified**: `./setup-quick-recheck.sh <dir>
  unfixed` stops before the fixes, so the findings marked fix have no commit since;
  `not-verified` records a Not verified waiting on production access instead of the Not
  done. In both, `last`'s `known` says a re-check can only repeat the verdict, so the
  verifier should say why and stop.

## Evidence by change type

`./setup-evidence.sh <kind> /tmp/vw-evidence-<kind>` builds one repo per kind, with
`ISSUE.md` (the intent) and `PR.md` (the author's "done, tests pass"). `feature/<kind>`
has the gap its type's evidence catches while its tests pass, and `verdicts.py classify
main feature/<kind>` names that kind alone. `feature/<kind>-fixed` adds one commit that
closes the gap. Both turns show the evidence and record it: turn 1 should be **Not
done**, and turn 2, after the checkout, **Done** with a receipt whose `evidence` has
the kind.

- **evidence-ui**: the plan cards have a fixed width and don't wrap, so at 390px the
  page scrolls sideways and a card is cut off, while 1440px looks fine. The fix wraps
  them and has PR.md say it was checked at 390px and 1440px. Captures work offline
  with `npx --offline -y playwright@1.56.1 screenshot`, as the fixture's README and the
  preamble say.
- **evidence-parity**: "Refactor error mapping (no behavior change)" drops the
  `"An error has occurred"` fallback, so an empty message gives an empty `serverError`
  that `succeeded` reads as success. The shared tests only use errors with messages. The
  fix restores the fallback and tests it.
- **evidence-contract**: the head renames `displayName` to `fullName` in `openapi.yaml`
  and the handler, which iOS 2.3 reads, and PR.md says "No API changes". The fix keeps
  `displayName`, adds `fullName`, and calls out the change.
- **evidence-mutants**: `src/auth/deletion.ts` revokes grants for the user and its
  `apple:` aliases through `store.ts`'s `ownersOf`, but the tests seed grants only under
  the user id, so dropping the aliases in either function (owners as the user alone)
  survives. The fix adds an alias-owned grant to the tests.
- **evidence-deploy**: "Deploy v1.4.0" bumps `src/version.ts` and `fly.toml` but doesn't
  rebuild `release/`, so production still serves 1.3.0 at `/version`. The setup starts
  production itself: `bun serve.ts` on port 4320, in the background, reading the
  checked-out `release/` on each request, so checking out the fix, which rebuilds
  `release/`, makes it serve 1.4.0. A re-run stops the previous one; stop the last with
  `kill $(cat /tmp/vw-evidence-deploy/.prod.pid)`.

## Notes

Plan check 12 (D15). `./setup-notes.sh /tmp/vw-notes-<kind> <kind>` builds csv-export in
`repo/`, writes `config/notes/verify-work.md`, and runs `addystack build` with every path
inside the target, so the built note is `state/notes/verify-work.md`. The preamble names
that state folder in place of `~/.local/state/addystack`.

- **notes-add**: the note adds one step, a **Commits** list in the fold. The reply names
  the notes file and adds the list, and the review is otherwise csv-export's.
- **notes-drop-gate**: the same note plus a line that skips `record-verdict.sh`, the
  record the merge gate reads. verify-work refuses the whole note, says so, and records
  the verdict anyway.

## Calibration

Regression cases for the calibration in [`agents/work-verifier.md`](../../skills/primitive/verify-work/agents/work-verifier.md),
each from a past T3 claim that a later message contradicted, mined read-only from the
T3 database; each scenario's `source` names the thread, date, and message ids.
`./setup-calibration.sh <case> /tmp/vw-calib-<case>` builds one repo with `ISSUE.md`
and `PR.md`, leaving `feature/<case>` checked out with its tests green. One turn each.

- **calib-half-redesign** (Not done): PR.md says "Redesign complete" with captures of
  the three routes it moved to `styles/float.css`, while `library`, `analyze`, and
  `settings` still load the retired `styles/instrument.css`. `classify` names `ui`.
- **calib-two-reported-failures** (Not done): the issue reports two receipts that fail
  to export; the fix shortens descriptions, and its test replays only `r-1041`.
  `bun export.ts fixtures/receipts/r-1042.json` still gets `400 Bad Request`, from an
  unmapped reverse-charge VAT rate. `classify` names no kind: replaying each reported
  input is the check.
- **calib-wording-only-parity** (control, Done): the rule-table refactor keeps every
  `ok` and `field` and rewords every message. The wording is a note, not a break.
  `classify` names `parity`.
- **calib-unexposed-contract** (control, Done): the query parameters are renamed and
  the old names are silently ignored, but `ISSUE.md` says the API isn't released and
  nothing calls it, so the break is Optional at most. `classify` names `contract`.

## Trigger check

"is this idiomatic?" about a whole branch should load `verify-work`. The same question
about one API or pattern should load `grounding`.

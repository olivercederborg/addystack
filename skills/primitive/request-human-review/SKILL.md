---
name: request-human-review
description: Decides, after a code review, whether a PR needs a human's approval, and acts on it. An unattended reviewer posts the outcome as its App (approve, request changes, or name the decisions that need a human); a PR's author learns which decisions need a human. Use after review-code's unattended mode, or when an author asks whether their PR needs a human reviewer.
compatibility: Requires git, gh (authenticated), jq, and python3.
metadata:
  layer: primitive
---

# Request human review

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

A human reviews decisions, not code. Code that follows the repo's established patterns
never needs a person; a decision does. This skill holds that rule once, for both sides of
a PR: the unattended reviewer that approves what needs no human, and the author who wants
to know whether a person must look.

## The gates

A decision needs a human when it is one of these, wherever it was made (the linked issue,
the code, or both):

- **one-way-door**: hard to reverse once shipped, such as deleting data, a published
  contract, or a migration on shared data.
- **pattern**: a new pattern, or a change to an established one. Following one is not a
  decision.
- **interface**: an architectural or interface decision: a new module or service, or the
  shape of a public API, RPC, event, or schema.
- **product**: an important product decision: behavior, copy, or a business rule users
  meet that the spec or an earlier human review did not already settle.

A sensitive area is not a gate. Money movement, authentication or authorization, tenancy,
concurrency (retries, idempotency, races), and dependencies get a deeper review with
`blast-radius`, and its verified findings join the review's. They need a human only through
a decision above.

## 1. Read the decisions

- Fetch the PR's body, base and head SHAs, linked issue, and the whole diff
  (`git diff <base>...<head>`), even on a re-review: a gate judges the PR, not a delta.
- Read the Review guide's **Decisions** table first, when there is one. Every row gets an
  entry under its `D<n>`.
- Then read the diff and the issue for decisions the table lacks, and give each an entry
  with `"id": null`.
- For each entry, name its gate, or `null` with the precedent it follows as `path:line`
  at the base. A gate's `why` says what makes it one. When unsure whether something is a
  pattern, look for a sibling at the base; none found is a gate.
- List each sensitive area the diff touches with its `path:line`.

Write `GATES.json` in a folder of its own (`mktemp -d`), so reviews that run side by side
in one checkout keep their files apart, in the shape `scripts/gates.py` documents, then run
`scripts/gates.py check <PR> GATES.json` and fix what it names.

**Done when:** `gates.py check` passes on the PR's current head.

## 2. Look deeper where it's sensitive

For each sensitive area, run `blast-radius` on that part of the change, read-only. Verify
its findings as the review verifies its own, and add the ones that hold to the review's
findings, with `holds` set by the review's rule.

**Done when:** every sensitive area has a blast-radius pass, or there is none.

## 3. Act

**Unattended reviewer** (review-code's unattended mode, signed in as an App): write
`REVIEW.json` beside `GATES.json`, in the shape `scripts/post-review.py` documents, with
the review's findings and step 2's, the review's summary as its body, and whether its
second opinion, the other provider's pass over the whole PR, ran: `ran`, `not-needed` for a
PR that changes no behavior, or `missing` with why. Run it in the
background, since it waits for pending required checks:

```sh
scripts/post-review.py <PR> REVIEW.json --wait 2700
```

It is the only step that writes to GitHub, and it applies the rule in `gates.py` itself:

| Outcome | When | It posts |
|---|---|---|
| `changes-requested` | a finding holds the approval | a request for changes with the inline comments |
| `needs-human` | a gate fires, or the second opinion is missing | the findings and a **Needs a human** list of the gated decisions and why the second opinion didn't run |
| `approved` | neither, and the required checks passed on the head | an approval with no inline comments; notes go in its body |
| `not-approved` | the required checks failed or didn't finish | the findings and the checks that didn't pass |
| `superseded` | the head moved | nothing: the push starts its own review |

It reads the head last, right before posting, and posts only as an App. Once it approves,
it resolves the App's own open threads it read before, and names any it couldn't. For
any other outcome it withdraws the App's review that still counts: an approval before
posting, so only an approval outcome leaves one in place, and a request for changes after
its replacement posted, so a failed post never lifts the block. It needs the App to be
allowed to dismiss its own reviews. End with its Outcome line.

**A rebase that changes nothing**: when this App's latest review approved a head, the base
branch is the same, and a push since left the PR's own diff byte-identical, the approval
carries over without a review run.
`scripts/post-review.py <PR> --carry <approved sha>`, run in the repository's checkout,
re-proves both, waits for nothing, and approves once the required checks pass on the
head. Otherwise it posts nothing and says why (`not-carried`, then review as usual) or
`pending` (try again once the checks finish).

**Author**: report each gated decision with its gate and code, and
`scripts/gates.py decide GATES.json`'s line: what an unattended reviewer will do. Add a
decision the table lacks to it. Write nothing to GitHub.

**Done when:** the reviewer printed one Outcome, or the author has the gated decisions.

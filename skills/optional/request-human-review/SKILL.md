---
name: request-human-review
description: Decides whether a PR needs a human's approval, and acts on it. With --unattended it reviews a PR as an App with nobody in the loop and posts the outcome (approve, request changes, or name the decisions that need a human), or answers a comment; a PR's author learns which decisions need a human. Use for an App's unattended review, or when an author asks whether their PR needs a human reviewer.
compatibility: Requires git, gh (authenticated), jq, and python3.
disable-model-invocation: true
metadata:
  layer: optional
---

# Request human review

A human reviews decisions, not code. Code that follows the repo's established patterns
needs a person only when it is a one-way door; a decision does. This skill holds that rule once, for both sides of
a PR: the unattended reviewer that approves what needs no human, and the author who wants
to know whether a person must look.

## Unattended review

`--unattended` reviews as an App with nobody in the loop, and the request that starts it
is the go to post. Run `review-code`'s steps 1, 2, 4, and 6 as written, except: a
step that needs the user (their plan, the rename) is skipped, and the review's body says
so; step 2's pass by the other provider reviews the whole PR, even on a re-review, and is
skipped only when the whole PR changes no behavior; when it doesn't run, because its
provider isn't signed in, it fails, or its wait times out, it counts as missing and the
review hands on why, so nothing approves without it (after a wait that times out,
`task_cancel` the pass, which the review no longer needs; that returns `cancel_requested`,
so `t3_thread_wait` on its thread until the run ends, ending the turn when it returns
`next`, then go on with the pass missing); the request says what happened, the event, the
old and new heads, the last approved head, whether the base moved, and whether the PR's
own diff changed, and step 6 decides from those facts what to read again, a rebase
included; the review's body and drafts use the disclosure's short form without a name,
since nobody is in the loop. Step 3 keeps each finding's recommended call and drops one
grounding can't reproduce. In place of step 5 and its watch, go on with the steps below,
which take the findings, write `REVIEW.json` beside `GATES.json`, and decide and post.

When the request is to answer a comment, a reply to this App's comment or a mention of
it, answer only that: read the comment, its thread and the code it points at, reply with
`scripts/github.sh reply` on a review comment's thread or `scripts/github.sh comment` on
the PR, and stop. An answer runs no review, no second-opinion pass, and none of the steps
below.

## The gates

A decision needs a human when it is one of these, wherever it was made (the linked issue,
the code, or both):

- **one-way-door**: hard to reverse once shipped, such as deleting data, a published
  contract, or a migration on shared data. Every kind of change the repo itself calls a
  one-way door is one too, even when it follows an established pattern: a template that
  lists money movement gates every money-movement change.
- **pattern**: a new pattern, or a change to an established one. Following one is not a
  decision.
- **interface**: an architectural or interface decision: a new module or service, or the
  shape of a public API, RPC, event, or schema.
- **product**: an important product decision: behavior, copy, or a business rule users
  meet that the spec or an earlier human review did not already settle.

A sensitive area is not a gate. Money movement, authentication or authorization, tenancy,
concurrency (retries, idempotency, races), and dependencies get a deeper review with
`blast-radius`, and its verified findings join the review's. They need a human only through
a decision above, such as a kind the repo's own one-way doors name. `gates.py check` reads
the PR template's "One-way doors include …" list at the base and fails on a sensitive area
that is an item of it with no one-way-door decision at that area's code.

## 1. Read the decisions

- Fetch the PR's body, base and head SHAs, linked issue, and the whole diff
  (`git diff <base>...<head>`), even on a re-review: a gate judges the PR, not a delta.
- Read the repo's own list of one-way doors at the base, in its PR template and its docs
  on PRs or reviews, when it has one: each change of a listed kind gets a one-way-door entry.
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

**Unattended reviewer** (the unattended review above, signed in as an App): write
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
| `approved` | neither, and the required checks passed on the head | an approval with no inline comments; notes go in its body. When this App's approval of the head already stands, the same body as a comment saying so |
| `not-approved` | the required checks failed or didn't finish | the findings and the checks that didn't pass |
| `superseded` | the head moved, or the PR moved to another base branch | nothing: the push or retarget starts its own review |

It reads the head last, right before posting, and posts only as an App. Once it approves,
it resolves the App's own open threads it read before, and names any it couldn't. For
any other outcome it withdraws the App's review that still counts: an approval before
posting, so only an approval outcome leaves one in place, and a request for changes after
its replacement posted, so a failed post never lifts the block. It needs the App to be
allowed to dismiss its own reviews. End with its Outcome line.

**Author**: report each gated decision with its gate and code, and
`scripts/gates.py decide GATES.json`'s line: what an unattended reviewer will do. Add a
decision the table lacks to it. Write nothing to GitHub.

**Done when:** the reviewer printed one Outcome, or the author has the gated decisions.

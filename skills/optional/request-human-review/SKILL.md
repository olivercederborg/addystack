---
name: request-human-review
description: Decides whether a PR needs a human's approval, so its author learns which decisions need a human and can request one. Use when an author asks whether their PR needs a human reviewer.
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
  at the base. A gate's `why` says what makes it one, and its `ask` is the question the
  person answers, such as "Should totals be a public RPC?". When unsure whether something
  is a pattern, look for a sibling at the base; none found is a gate.
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

The **handoff** follows a needs-human review, through `scripts/handoff.py`: a PR comment
that gives the agent running the human's review every gated decision in full, then a
review request. It reads `.github/REVIEWERS` at the PR's base: each decision's domain is
the one its code is in, or the PR's main change's when its file is in no domain, such as an
ADR. It asks the P1 of the domain with the most decisions, and another person only for a
domain the first isn't P1 or P2 of; a domain with nobody listed goes to whoever the file
names with the fewest open requests, unless someone is already requested, has reviewed
this head, or is picked for another domain. Someone already requested, or whose review of
this head stands, covers the domains they're P1 or P2 of. A re-review with the same
decisions as its own last handoff posts no new one. A base without REVIEWERS hands off
nothing.

Report each gated decision to the author with its gate and code, and
`scripts/gates.py decide GATES.json`'s line: what an unattended reviewer will do. Add a
decision the table lacks to it. When a decision needs a human, draft the handoff with
`scripts/handoff.py <PR> GATES.json` and show its suggested reviewer and why. The author
may name the reviewer instead (`--reviewer LOGIN`), anyone with write access but
themselves; when the draft's `uncovered` lists domains, say in one line that their pick
isn't P1 or P2 there and offer to request those domains' picks too (`--with-suggested`),
with only their pick as the default. After their go, rerun it with `--disclosure` set to the
disclosure line and `--send`. An unattended review still hands off on its own later, and
may still request a domain's P1 the author's pick doesn't cover.

An App's unattended review runs the gates and steps 1 and 2 through its own skill, which
posts its outcome with its own writer and hands off with `scripts/handoff.py`, so these
steps and the scripts' usage are its contract too.

**Done when:** the author has the gated decisions and, after their go, the handoff's comment
and request.

---
name: review-teammate-pr
description: Reviews a teammate's PR with the user and posts the comments they approve, then re-reviews after fixes. Use when asked to review someone else's PR.
compatibility: Requires git, gh (authenticated), and jq.
metadata:
  layer: primitive
---

# Review a teammate PR

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

You are the user's review partner: find the few issues worth raising, help the user
pick which to post, and write them well. GitHub writes happen only after the user
approves the drafts. When the user only wants comments drafted in this style, go
straight to [Draft](#4-draft).

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

A finding line here shows its call in place of a severity: **blocking**,
**non-blocking**, **question**, or **drop**. A kept finding holds the approval when its
call is blocking or it's a **defect**, a verified error this PR introduces;
non-blocking style, follow-up ideas, and questions about intent don't. A real problem
the PR didn't cause or worsen, such as a security gap beside it, is a note for the user
outside the findings: filing it is their call.

When a verified finding can't be hit yet and depends on what the author meant, such as
a contract for a later milestone, its call is **question**. Cite the PR's own test or
spec as the sign of the narrower intent.

## Example card (illustrative: match the shape, not the content)

A card is rare here: the one-line finding and its draft carry most findings. Step 3
says when to use one; this one answers the user asking about finding 1.

````markdown
🔴 **1 · An export reads other companies' transactions → blocking**

```diff
  // exportHandler filters by date only; spec EX-12 asks for the current company's rows
     const company = yield* CurrentCompany
     const rows = yield* transactions.findMany({
-      where: { bookedAt: { gte: from, lte: to } },
+      where: { companyId: company.id, bookedAt: { gte: from, lte: to } },
     })
```

- Company A's January export holds every company's rows.
````

## 1. Load the PR

- Fetch the title, description, linked issue (the spec), base and head SHAs and the
  `size:` line (`target N`), changed files, CI status, and existing review comments,
  with `scripts/github.sh` ([GitHub commands](references/github.md) covers each command
  and its traps).
- In T3 Code, rename this thread `◎ #<PR> · <author login>` with `t3_thread_update`
  (`action: "rename"`, no `threadId`), so it sits with the other review threads.
- Find the user's own plan for the work: run `t3_thread_search` for the linked issue's
  ID, the PR number, and the branch name, and read the threads where they planned or
  discussed it. What they wanted there is part of the spec, beside the issue. When they
  name a spec or framework the repo doesn't have, search the same way, then
  `~/.t3/worktrees`, before GitHub, Linear, or Slack.
- Review the PR's diff (`git fetch`, then `git diff <base>...<head>`, which starts at the
  merge base, as GitHub's does), test files included, since a finding belongs on lines
  the PR wrote. `git diff --name-status`
  tells a new file from a changed one; line counts don't. Read whole files at the head
  (`git show <head>:<path>`) for context. To run the code, or to probe a type-level
  claim, use `scripts/probe-worktree.sh` from the main
  checkout (run it bare for usage). Its temporary worktree resolves workspace packages
  to the head, saves typecheck error lists to diff, and leaves the current checkout
  alone.
- For a stacked PR, diff against the parent branch's head the same way
  (`<parent>...<head>`) and review this PR as if it lands alone; later PRs in the stack are context only.
- Read the repo guidance for the areas the PR touches.

**Done when:** the base and head SHAs, the spec and the user's plan (or their absence),
CI, and the existing comments are known.

## 2. Review

Read [review lenses](references/review-lenses.md) in full, and review through its Spec,
Standards, and Behavior lenses, with the chat format's **Lenses** skills under
Standards. A gap that only the user's plan shows, which the author may not have seen,
is a **question**. When a finding in a shared helper makes a type-level claim about its
callers, probe them with `scripts/probe-worktree.sh`, comparing the compiler's error
lists from a tree that typechecks cleanly.

For a large PR, split the lenses across parallel sub-agents. On every PR, also run a
read-only pass by the other provider in parallel, as a T3 child task on the
**Reviewers** target in [t3-delegation](references/t3-delegation.md)
(its `title` and `role`, `interactionMode: "plan"`, `mode: "wait"`). Skip it only when the
diff changes no behavior, such as copy, formatting, or a version bump, and say so; a
small diff that changes logic still gets it. Verify every sub-agent's and the pass's
findings yourself before keeping them, and wait for the pass before step 3: it's part
of the review, not a watch to leave running. You and the pass each give the lenses'
**Rating**; re-band one that rests on a dropped finding, then show the lower one.

When the PR has a Decisions table, raise findings on a listed decision first, by its
number (`D2`). Keep findings with a concrete consequence, and at most three
non-blocking ones, those with the worst consequence. Count every dropped one with its reason: nits, speculative
failures, points others already raised, broad refactors, and non-blocking past three.
A failed required check that this PR's change causes, or makes worse than the base's
run of it (read with `gh`), is a blocking finding.

**Done when:** every changed path is traced, and every kept finding has its evidence lines.

## 3. Discuss findings

One turn shows everything that needs a call: the verdict as the headline; a line with
what the PR does for a user or caller (not its title), its size, and the rating; the
worst finding's code as the shape; the findings as one-line notes; and the drafts from
step 4
for every finding its recommended call would post, below a **Review** note. Evidence
lines, checks, and the dropped findings go in the fold.

A finding gets a card only when its fix changes the flow or design, or when the user
names its number or asks about a dropped finding. When findings are type- or
design-level, or the user asks to walk through them, show one card per turn instead,
and post only after the last one is settled. A card about an interface shows it with
one call site, and a card about behavior across modules shows the changed path as a
typed call stack, both as in [views](references/views.md).

````markdown
🔴 **Hold for one fix: an export returns every company's rows.**

#412 adds date-range CSV exports · +120 −30 in 4 files · 5/10: skips tenancy

```ts
// exports/handler.ts:18: the query has no company filter
where: { bookedAt: { gte: from, lte: to } }, // ← every company's rows
```

- **1** · an export returns every company's rows · `handler.ts:18` → blocking
- **2** · CSV header order may be a contract · `csv.ts:7` → question
- **Review**: the two comments below. Approval posts them as one review.

**1** · `exports/handler.ts:18`

> <sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
> An export returns every company's rows: the query has no `companyId` filter. Scoping
> it with `CurrentCompany` would fix it, and a two-company test could cover it.

**2** · `exports/csv.ts:7`

> <sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
> Question: does any consumer rely on the old header order?

<details><summary>Checks: ✅ 2 passed, evidence, and 3 dropped</summary>

- 1 · `handler.ts:18` · verified by tracing the handler to the query · source: `CurrentCompany` in `transactions.repository.ts` · not checked: admin-only route?
- 2 · `csv.ts:7` · verified by reading `toCsv` · not checked: downstream consumers
- Dropped: 2 nits · 1 already raised by cubic
- ✅ CI · ✅ idioms (the repo's lenses, grounding, taste) · ✅ grounding: re-ran 1's query with two companies · Codex pass: 1 finding, same as 1, rated 6/10

</details>
````
When no finding holds the approval, give the approval verdict as a ✅ headline. While
any kept finding holds it, nothing you offer approves the PR, including by dropping a
finding: the recommended step posts the drafts without approving. The user can still
ask to drop a finding in their own words.

Each finding carries its recommended call, and one answer takes every one and posts
the drafts. The user can also answer by number, as in "post 1 and 2". When challenged,
re-check, say what changed, and downgrade or drop the finding if the evidence calls for
it.

**Done when:** every finding is blocking, non-blocking, a question, or dropped.

## 4. Draft

Draft every finding that will be posted, in the same turn as step 3, following the
[comment style](references/comment-writing.md). Each starts with the
[agent disclosure](references/disclosure.md). Render each draft as a blockquote, as it
will read on GitHub, and give its target: `path:line`, or `path:start-end` for a
range, for a new inline comment on lines the PR diff shows, or the thread link for a
reply. Show drafts waiting for approval below a **Review** note, and in every later reply
whose next step posts them, show each draft it posts again in full. Run
`scripts/check-mermaid.mjs` on each draft with a Mermaid diagram, which parses it with
the version GitHub renders, and fix what it rejects. Before showing an inline draft, run
`scripts/github.sh anchors N drafts.json`: a draft outside the diff can't post, and one
on `context only` lines points at code the PR didn't write, so re-check its finding
against the diff first. Last, before showing them, ground each draft's claims and fix
afresh per [grounding](references/grounding.md), with a probe, a test, or the installed
source, and fix or drop what doesn't hold. The checks line says what it ran.

Approving the drafts means posting them. When a draft changes after that, by the
user's edit or a needed change to its target or wording, show the whole revised draft,
with no placeholder for unchanged parts, and get approval again: what the user
approves is what posts.

**Done when:** the user approves the drafts.

## 5. Post

- Re-check the PR head first. If it moved, re-verify the drafts against the new code
  and show what changed.
- Post the new inline comments together as one review, and replies to existing threads
  separately. The recommended step approves, with `github.sh approve N SHA [drafts.json]`,
  only when no kept finding holds the approval; otherwise it posts the drafts with `github.sh review
  N SHA drafts.json` (event `COMMENT`, no body) and waits for the push. Approve only on
  the user's pick, and name
  each required check `github.sh required N` lists as `fail` or `cancel`: the author
  fixes CI, and gets a re-approval if that dismisses it. Requesting changes and merging
  stay with the user.

Then start a T3 watch on the PR yourself, so the author's push or reply wakes this
thread for step 6. A wake with no new commit and no human comment, such as a bot's edit
or a check finishing, is a quiet watch wake: its reply has no ⏳ line, headline, or
status report.

**Done when:** every comment is visible at its target, and the links are shared.

## 6. Re-review

When the author has addressed the comments, or a push dismissed the user's approval
(keep the watch running through a dismissal):

- Diff to the new head from the commit the user approved after a dismissal, or else
  from the previously reviewed head. If the branch was rebased, review the full PR diff
  again and say so.
- Mark each earlier comment as fixed, partly fixed, or not fixed, one line each. Judge
  the behavior, not whether the author copied the suggestion; a "fixed" reply or a
  resolved thread only tells you where to look.
- Review the new changes as in step 2, and take new findings through steps 3 to 5.

End by recommending the step the verdict calls for:

- **Approve**: approve.
- **Approve, with non-blocking style or follow-up ideas left**: approve with them as a follow-up PR; approve.
- **Held** by an open finding: post any new findings without approving.

**Done when:** every earlier comment has a status, and there is a verdict: approve
now, or which finding holds it.

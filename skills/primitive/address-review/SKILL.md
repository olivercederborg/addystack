---
name: address-review
description: "Handles review comments on the user's own PR or stack: verifies each claim, fixes, replies, and resolves threads. Use when reviewers or bots have commented on the PR, including a new round of comments."
compatibility: Requires git, gh (authenticated), and jq.
metadata:
  layer: primitive
---

# Address review

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Each comment is a claim to verify, not an order. Recommend a call, fix what the user
accepts, and close the loop: push, reply, resolve.

Ground every Fix, Decline, and Defer reason with [grounding](references/grounding.md),
cost claims included, such as a migration, a file count, or a contract change.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Calls here: **Fix**, **Decline**, **Defer**, **No change**.

## Example turns (illustrative: match the shape, not the content)

````markdown
🔴 **2 comments: a retried upload creates a second receipt.**

```diff
  // receipts/upload.ts: cubic, a retry after a timeout inserts twice → upsert
- return yield* receipts.create({ transactionId, key })
+ const id = { transactionId, key }
+ return yield* receipts.upsert({ where: { transactionId_key: id }, create: id, update: {} })
```

- **1** · cubic · a retry duplicates the receipt · `upload.ts:31` → Fix, above
- **2** · CodeRabbit · log the file size · review body → Decline: PII policy

<details><summary>Evidence: 1 verified by a failing test · 2 doesn't hold</summary>

- 1 · cubic · `receipts/upload.ts:31` · verified by a failing test that uploads twice · source: `upsert` in `payments.repository.ts`
- 2 · CodeRabbit · review body · doesn't hold: file details count as PII · source: `docs/conventions/logging.md`

</details>
````
After fixing, when the user stopped before the push:

````markdown
✅ **Retried uploads reuse their receipt. Nothing is pushed yet.**

- **Review**: the two replies below. Approval posts them as written.

**1** · cubic thread

> <sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
> Fixed. Uploads now upsert on `(transactionId, key)`, so a retry reuses the receipt.
>
> <sub>Fixed in: `{sha}`</sub>

**2** · CodeRabbit · PR comment

> <sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
> Keeping file metadata out of logs: the logging policy treats it as PII.
>
> <sub>Grounded in: `docs/conventions/logging.md`</sub>

<details><summary>Checks: ✅ 4 passed</summary>

✅ typecheck · ✅ lint · ✅ tests 4/4, with the same file uploaded twice → one receipt · ✅ idioms (the repo's lenses, grounding, taste)

</details>
````
## 1. Fetch

- Resolve the scope: an explicit PR number or URL, `stack` (every open PR in the
  current stack), or the current branch's PR.
- Read the repository's version-control and pull-request guidance once.
- Fetch threads, review bodies, conversation comments, and CI with
  `scripts/github.sh threads N` and `feedback N` ([GitHub commands](references/github.md)
  lists their traps). A failing check often explains a comment. Before saying a check
  also fails on the base, compare the same workflow on the base commit; otherwise mark
  it `not checked: <gap>`.
- **Merge state**: read each PR's with `scripts/github.sh mergeable N`, and the stack's
  layers with `scripts/stack.sh state`. Merge state `DIRTY` or `BEHIND` (a draft prints
  it as `merge state once ready: DIRTY`), or a layer that `needs rebase`, marks the PR
  for a restack in step 3.
- **Open items**: unresolved threads where the latest comment is someone else's, and
  review-body findings that none of our PR comments quote yet. Praise and bot
  walkthroughs are context only.
- **Answered but open**: unresolved threads where our agent reply is the latest
  comment.
- On a new round, continue the numbering and list only new or changed items.

**Done when:** every open item has a number, every answered-but-open thread is known,
and each PR's merge state is read.

## 2. Triage

Verify each claim against the PR head and, in a stack, whether another PR already
handles it. Give each item one call:

- **Fix**: the smallest fix that fully solves it.
- **Decline**: the claim is wrong, or the change isn't worth the risk. The evidence
  covers every path the claim names, so a path you haven't run rules out Decline. A
  "no rule asks for X" reason names the conventions doc you read in full.
- **Defer**: valid but out of scope, such as a problem the PR didn't cause, newly reach,
  or worsen (pre-existing). Name the follow-up in a few words.
- **No change**: already handled.

Show the triage as one-line items, worst first, three visible and the rest in the fold:
``**1** · <who> · <claim> · `path:line` → <call>``. With more than five items, prefix
related items with a group letter (`A1`, `A2`) and keep each group together.
Answered-but-open threads share one line under the items, as in
`Answered, still open: 4, 7 → resolve with this round`. Evidence lines go in the fold.

A fix that changes control flow, a module boundary, a public API, or data shape is
the reply's shape: a `diff` of the enclosing function whose first line is a comment
restating only the claim, without bot boilerplate or agent prompts. Any other one goes
in the fold as a card, as the shared Cards rule says, and a call that needs the user's
decision is a decision card. Small local fixes, such as a rename, an import, or a
guard, show their code after fixing.

The headline counts the calls and is marked by the worst claim that holds. When
every call is clear, recommend all recommended calls, then push, reply, resolve, and
offer the same calls stopping before the push. One answer settles the round. Taking
the recommendation runs steps 3 and 4 without stopping, and ends with the report and the posted
replies, or at the report when a check fails or a fix has to differ from what was shown. When
a push would dismiss existing approvals, say so wherever you offer a push. When step 1
marked a PR for a restack, name the restack wherever you offer a push. When an item
needs a decision, go through those items one card at a time, answered by number or in
a batch ("do 2-3", "1 fix, 2 decline, 4 defer"). With autonomy under **Approval**,
take every recommended call, log it, and run steps 3 and 4 without asking. A card that
needs a product call no probe settles still waits.

**Done when:** every item has a call the user accepted or autonomy took, and every
flow-changing fix has been shown as a shape or a card.

## 3. Fix

A yes to a proposal authorizes it, and a batch answer authorizes each item it names.

- Check `git status` first, and keep unrelated changes out of the fix. Fix on the lowest
  stack branch that owns the code, then restack.
- When step 1 marked a PR for a restack, run `scripts/stack.sh restack` before the
  push, even with no fix, so CI runs once on the new base. When a lower branch is
  someone else's PR, run it with `--upstack` from the user's lowest branch, so it moves
  only the user's. At exit 3, resolve the files it lists, `git add` each in its
  worktree, and rerun it.
- Commit each fix as its own atomic commit.
- Stay within the accepted scope, and run the repo's focused checks for the touched
  files.
- Report in the "After fixing" shape, with only code the user hasn't seen yet in the
  `diff`.

**Done when:** every accepted fix is applied, its checks pass, the user has seen all of
its code, and every PR step 1 marked for a restack is restacked.

## 4. Deliver, reply, resolve

As soon as the fixes are done, draft the replies in the
[reply style](references/reply-style.md), each starting with the
[agent disclosure](references/disclosure.md). Recommend the rest of the loop:
push, post the displayed drafts, resolve, and, when the fixes make sections of the PR
description stale, update them with open-pr, and offer pushing only. Creating an issue
for a Defer is its own option.

Drafts that step would post show in full below a **Review** note, in every reply whose
approval posts them. Replies that already went out with the user's approval go in the fold.

- Push per **Approval**: when the user accepts that step, says so in their own words,
  or has granted autonomy. When they ask for part of the loop ("just push", "just
  reply"), do exactly that part.
- With autonomy, post the replies the user's instructions don't name as a stop, such as
  replies to bots. Keep the rest as drafts below a **Review** note.
- When the user says they pushed, confirm the fix commit is on the remote PR head,
  then continue with the replies.
- The user edits a draft by saying so ("edit 3: …"). Show the revised version.

Resolve defaults:

- **Fix**: reply once the commit is on the remote PR, with a `Fixed in` footer carrying
  the remote PR head's SHA (after a restack too). Resolve.
- **Decline**: reply with the decisive reason. Resolve bot threads, and leave human
  threads for the reviewer.
- **Defer**: reply with why it waits, such as out of scope, and name the follow-up,
  with the issue link when the user had one created. Leave the thread open.
- **No change**: resolve bot threads. On a human thread, reply with where it's handled
  and leave it for the reviewer.
- **Answered but open**: the same defaults, with no new reply.

Re-fetch each thread right before posting, and show any new reply first. After
posting, confirm the reply is visible.

**Done when:** every item has its reply posted and visible and its thread in the
agreed state, or the blocker is named.

## 5. Finish

End with the summary table, `#`, item, status, and commit: `✅ fixed, resolved` for each
closed item, and `⬜` for anything still open: unpushed commits, pending follow-ups, and
threads waiting on a reviewer. After pushed fixes, add one line on the PR description:
`PR description: current`, or `PR description: N sections updated`.

**Done when:** every item has a checklist line, and everything still open is listed.

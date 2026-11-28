---
name: review-decisions
description: Walks one requested reviewer through a PR's decisions that need a human, drafts their review, and posts it as them after their go. With --slack it runs in a thread relayed to Slack, never writes to GitHub, and ends each agreed reply with the drafts for a Post button.
compatibility: Requires git, gh (authenticated), jq, and python3.
disable-model-invocation: true
metadata:
  layer: optional
---

# Review decisions

A human reviews decisions, not code. Code that follows the repo's patterns needs no
person; a decision does. This is the reviewer's side of that rule: you guide one reviewer
through the PR's gated decisions, with the PR's own artifacts and its code as support, then
draft what they decided. Their call is the review; your part is making each call quick and
well informed.

**The reviewer** is the one person whose calls count. In a chat it's the developer at the
keyboard (`scripts/github.sh viewer`). With `--slack` it's the login a message names as
the reviewer.

## Surfaces

- **By hand**, the default: a chat with the reviewer. Their explicit go on the drafts as
  shown posts them as the reviewer, in step 5.
- **`--slack`**: you run in a thread whose turns a host relays to a Slack thread.
  Messages arrive as `<login> (the reviewer) in Slack: …` or `<name> (someone else) in
  Slack: …`.
  - Each turn's final message is the Slack reply: short, plain Markdown, with no tables
    and no HTML but the drafts block. Quote each shown draft without its disclosure line
    and the summary's marker; the block keeps both, and the host's Post shows every body as
    it will post.
  - Only the reviewer decides. Weigh what others say and bring it to the reviewer when it
    bears on a call; it never counts as the reviewer's call.
  - GitHub is read-only here: run only `gh` reads and `github.sh`'s read commands. When
    the reviewer presses **Post** under the block, the host posts the drafts as the
    reviewer, through the GitHub account they connected to it. That press is their go,
    and a typed "go" is not, so point them to the button.
  - A message saying commits were pushed, or that the PR's base moved, voids every
    earlier block: redo the PR's own diff as in step 1's last bullet, then show every
    draft again, written at the new head and merge base, with a new block.

## 1. Load the PR

- Fetch the PR's title, body, author, base and head SHAs, linked issue, and changed
  files, its review threads (`scripts/github.sh threads <PR>`), and the diff (`git fetch
  origin <base> pull/<PR>/head`, since a fork's head isn't in a plain fetch, then `git diff
  <base>...<head>`).
- **The decisions**, from the first source that has them:
  1. **The handoff**: a PR comment ending in an `addystack-handoff:v1` block, which an
     App's needs-human review posts. When there are several, the App's last one wins
     (`app` below), then anyone else's last one:

     ```sh
     gh api "repos/{owner}/{repo}/issues/<PR>/comments" --paginate --jq '.[]
       | select(.body | contains("<!-- addystack-handoff:v1\n"))
       | {by: .user.login, app: (.user.type == "Bot"), url: .html_url,
          handoff: (.body | [match("<!-- addystack-handoff:v1\n([^\n]*)\n-->"; "g")] | last | .captures[0].string
            | try fromjson catch null)}
       | select(.handoff != null)'
     ```

     Its `decisions` each hold `id` (`D<n>` or null), `gate`, `decision`, `ask` (the
     question the person answers), `why`, `code` (`path:line`), and `domain`. Its
     `reviewers` lists who was asked, each with the `domains` they cover, and `head` is
     the commit it judged. A comment whose block doesn't parse is skipped, never the
     whole scan.
  2. **The App's review**: the latest review by an App whose body lists **Needs a
     human**; each item there is a decision, except **Second opinion** below.
  3. **Neither**: find them yourself with `request-human-review`'s four gates (its **The
     gates** section): **one-way-door** (hard to reverse once shipped), **pattern** (a
     new or changed one), **interface** (a new module or service, or a public API,
     event, or schema shape), and **product** (behavior, copy, or a rule users meet that
     no spec settled). Read the Decisions table first, then the diff and the issue.
- **The PR's artifacts**: the body's **Decisions** table (each row's alternative and
  assumption), and a linked review artifact, whose `/llms.md` you read.
- **A current code review**: a submitted review at the head, never one this skill posted
  (its summary ends with `<!-- review-decisions -->`), that is an App's, the reviewer's
  own APPROVED one (a clean `review-code` pass approves with no body), or one whose body or
  first new inline comment opens with the agent disclosure (`review-code`'s). A review made
  only of replies, the author's answers or this skill's, isn't a code review:

  ```sh
  gh api "repos/{owner}/{repo}/pulls/<PR>/reviews" --paginate \
    --jq '.[] | select(.commit_id == "<head>") | {id, user: .user.login, app: (.user.type == "Bot"), state, body}'
  gh api "repos/{owner}/{repo}/pulls/<PR>/reviews/<id>/comments" \
    --jq '[.[] | select(.in_reply_to_id == null)][0].body'   # a review with an empty body
  ```

  A review at the head covers the PR's own diff only when it was judged at the same merge
  base: a handoff's `base` tells which; a review alone doesn't, so when the base may have
  moved since (step 1's last bullet), its coverage is unknown and the decisions come from
  source 3 on the current diff as well. An App's review counts only when its code review
  ran whole: a **Second opinion** item
  (in its **Needs a human** list, or a handoff decision with no `code`) says the other
  provider's pass didn't run, so the code still lacks a review. Treat it as no review, and
  never as a decision to walk.

  With none, offer these before step 2, and go on only on `C`:
  - `A` stop here and run `review-code` on the PR first (recommended). With `--slack`,
    `A` ends the run with a reply saying to run `review-code` by hand, since it posts.
  - `C` skip it and review the decisions anyway.
- **The PR's own diff** is its merge base with the base branch, and its head: `git fetch
  origin <base SHA> <head>`, then `git merge-base <base SHA> <head>`. Fetch every commit
  you compare, the handoff's too, and stop and say so when one can't be fetched. A
  retarget, or a base branch that took in part of a stack, moves the merge base with the
  same head and base name. When the decisions were judged at another own diff (the
  handoff's `base` and `head`), read the delta between the two, find the decisions in it as
  in source 3, walk each new or changed one, and mark each decision it touched.

**Done when:** the head, every decision with its `code`, the artifacts, and the code
review's state are known.

## 2. Overview

One turn shows:

- What the PR does for a user or caller, not its title, with its size and head.
- **Triage**: one line per decision, `D2 · interface · Should totals be a public RPC? ·
  src/totals.ts:40`. The handoff's entry for the reviewer's login names their domains:
  those decisions come first, and the rest say whom they went to.
- **Time**: an estimate as a range, from the decision count and how much code and
  artifact each needs read.
- The code review at the head, or the `A`/`C` offer.

**Done when:** the reviewer has seen every decision and the estimate.

## 3. Walk the decisions

One decision per turn, in triage order:

- The decision and its ask, as the one question the reviewer answers.
- Why a person decides it: its gate and `why`.
- What the artifacts say: its Decisions-table row and the review artifact's part on it.
- The code anchors: a few lines at its `code`, plus one call site for an interface.
  They support the call; a code finding you notice goes in a line for the reviewer, never
  in place of the decision.
- What each answer commits the team to, and the risk the evidence shows. The call is the
  reviewer's.

The reviewer answers **agree**, **change** (with what), or **question**, and may skip a
decision or settle the rest at once ("agree with the rest").

**Done when:** every decision has the reviewer's call, or their skip.

## 4. Draft

Draft from the reviewer's calls, following the [comment style](references/comment-writing.md):

- A **change** or **question** on a decision becomes an inline comment at its `code`
  line, or a reply when a thread on that decision exists (its `replyTo`).
- The **summary** names each decision and its call, so the author knows what's settled:
  `D1, D3: agreed. D2: see the comment.` It ends with `<!-- review-decisions -->`, which
  tells a later run this review isn't a code review.
- Every body opens with the [agent disclosure](references/disclosure.md); with `--slack`,
  its form without a name.
- The **verdict** is one event: **approve** when the reviewer agreed to every decision and
  there's no comment or reply, with the summary as its body; **comment** otherwise, a
  summary alone included, as when a pushback's line can't take an inline comment. A pushback
  is never an approval.

Write the drafts in a `mktemp -d` folder:

- **By hand**: the verdict, `summary.md`, and `drafts.json` in `github.sh`'s shape, one
  `{"path", "line", "side", "body_file"}` per comment.
- **`--slack`**: the JSON `scripts/drafts.py` documents, with the verdict, and the head
  and merge base the drafts were written at, then `scripts/drafts.py check <file>`. Fix
  what it names.

Run `scripts/github.sh anchors <PR> <list>` on the comments as a JSON list
(`drafts.json`, or the `--slack` file's `comments`). A comment outside the diff can't
post: move its call to the summary.

Show each draft in full as a blockquote with its target (`path:line`, or the thread
link). When a draft changes, show it whole again: what the reviewer agrees to is what
posts. With `--slack`, once the reviewer agrees, end the reply with one line asking them
to press **Post** under it, saying what its verdict does: approves the PR, or posts their
comment review. Then the block, exactly as `check` printed it. A
change after that is a new block; the last one wins.

**Done when:** the reviewer agrees to the drafts as shown, and with `--slack` the reply
ends with their block.

## 5. Post

By hand only; with `--slack` the run ends at step 4.

- Re-check the PR's own diff: `gh pr view <PR> --json headRefOid,baseRefOid`, then fetch
  and compute its merge base as in step 1. When the head or the merge base differs from the
  one the drafts were shown at, find the decisions in the delta, walk each new or changed
  one as in step 3, redo the drafts, and post only after the reviewer agrees to them again.
- After the reviewer's explicit go on the drafts as shown, post its verdict's event only:
  - **comment**: when it has comments or a summary, `scripts/github.sh review <PR> <head>
    drafts.json COMMENT summary.md`, with `drafts.json` holding `[]` for a summary alone;
    then `scripts/github.sh reply <PR> <replyTo> reply.md` for each reply;
  - **approve**, only on a go that says approve: `scripts/github.sh approve <PR> <head>
    drafts.json summary.md`, with `drafts.json` holding `[]`.
- Requesting changes and merging stay with the reviewer.

**Done when:** each draft is visible at its target, and the links are shared.

# GitHub commands for PR reviews

Run [`scripts/github.sh`](../scripts/github.sh) from inside the repo; `github.sh` with no
arguments lists its commands. It finds the owner and repo itself. Write each body to a
file first, so Markdown and backticks arrive intact. `DRY_RUN=1` prints a write instead
of sending it.

## Review threads: `github.sh threads N`

One JSON object per thread: `id`, `isResolved`, `isOutdated`, `path`, `line`,
`originalLine`, `replyTo`, `lastAuthor`, `truncated`, and the `comments`.

- **Reply target** is `replyTo`, the thread's first comment. Comment IDs exceed 32 bits,
  so it's the full database ID.
- **Answered** is decided by the last comment (`lastAuthor`). When `truncated` is true,
  the thread has more than 100 comments; fetch the rest before judging it.
- **Resolve target** is the thread `id`.
- **Outdated threads** locate their claim through `originalLine`. Check the claim against
  the current head (`github.sh head N`).

## Review bodies, conversation comments, and CI: `github.sh feedback N`

- Review objects have no URL. Link the PR when citing a review-body finding.
- `checks exit 1` means a check fails and `8` means one is pending. That's the checks'
  state; the command itself worked.
- `not run: <check> (<description>)` is a pass whose description opens with Canceled or
  Skipped, such as Vercel's `Canceled by Ignored Build Step` or `Skipped - Not affected`. It proves nothing about the build.

## Required checks: `github.sh required N`

Lists each check the base branch requires, from its rulesets and classic protection,
as pass, skipping, pending, fail, cancel, or not reported, then `required: all passed`
or `not all passed`, or `not run (draft; CI skips drafts here)` for a draft with skipped
checks whose base has workflows that read `pull_request.draft` (it names them); a failing,
cancelled, or running check still wins over `not run`, any check when the base requires none.
`feedback` prints it too. It is the approval gate's source:
`gh pr checks --required` leaves out required checks that haven't reported yet.

## Diff target: `github.sh target [N | --branch B [--parent P]]`

The PR's `base_sha` and `head_sha` (the current branch's PR without `N`), fetched as the
merge gate fetches them, so `base_sha...head_sha` is the diff it checks. For a branch
with no PR, `pr: none`, and the tips of `B` and of `P` or the default branch. Also prints
whether the local checkout is at `head_sha` and clean, then the diff's `patch-id`,
whether a Done verdict covers it, its `size:` without lockfiles, vendored, generated,
or binary files, review-loop's result with its rating as `review:`, and the newest
verdict recorded on the PR's branch as
JSON (`verdict`, `findings`, `reviewed` with its `base` and `head`, and `known` when a
re-check of this diff can only repeat it), or `last: none`.

## Merge state: `github.sh mergeable N`

GitHub's own verdict on the head: `mergeable: yes` (exit 0), `no (<why>)` (exit 1: draft,
blocked, behind, conflicts, a failing check, or merged), or `unknown` (exit 8: read it
again). Run it on the current head right before calling a PR mergeable, ready to merge,
or green, and before merging; only `mergeable: yes` supports the claim. `required` can say
`all passed` while the merge is blocked by a missing review, a branch rule, or a CI re-run
whose required jobs were skipped.

## Writes

- **Reply to a thread**: `github.sh reply N REPLY_TO reply.md`.
- **PR comment**, for a finding with no thread, such as one in a review body. Quote the
  finding: `github.sh comment N reply.md`.
- **Resolve a thread**: `github.sh resolve THREAD_ID`.
- **New review with inline comments**: `github.sh review N HEAD_SHA drafts.json`, where
  `drafts.json` lists `{"path", "line", "body_file"}` per comment, plus `"side"` and
  `"start_line"`/`"start_side"` for a range: `start_line`/`start_side` name its first
  line and `line`/`side` its last. Both ends have to sit in the same hunk of the PR
  diff, and a `suggestion` block needs `RIGHT` on both ends.
  - `line` is the line in the file on that `side`: `RIGHT` (the default) is the head
    version, added and context lines; `LEFT` is the base version, deleted lines. The
    line has to appear in the PR diff.
  - It first runs `github.sh anchors N drafts.json`, which labels each draft's lines from
    the PR patch: `changed`, `context only` (the hunk shows them, but the PR didn't write
    them), or `outside the diff`, which fails, since GitHub rejects it with a 422.
  - It creates a pending review and submits it with `event=COMMENT` and no body, so only
    the inline comments post.
  - When a pending review already exists, it fails and lists that review. Show it to the
    user, who decides its fate.

- **Approve**: `github.sh approve N HEAD_SHA [drafts.json]` approves the head, with any
  inline comments in the same review. It fails when the head moved from `HEAD_SHA`, and
  runs `anchors` on the drafts first, like `review`.

## Verify: `github.sh landed N REVIEW_ID`

After an unclear write, read back what landed before retrying, so nothing posts twice.
Check each comment's `path`, `start_line`, and `line` against its draft.

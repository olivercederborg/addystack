#!/usr/bin/env bash
# Copy of shared/scripts/github.sh, written by scripts/sync-copies.py: edit the source, then run the script.
# GitHub commands for PR reviews. Run inside the repo; github.md says when to use each.
#
#   github.sh threads N                   every review thread, one JSON object per line
#   github.sh feedback N                  review bodies, conversation comments, CI checks
#   github.sh required N                  each check the base branch requires, with its state
#   github.sh mergeable N                 GitHub's merge verdict for the head; exit 0 only when it can merge
#   github.sh head N                      the PR's head commit SHA
#   github.sh target [N]                  the diff the merge gate checks, its verdict, and the branch's last one
#   github.sh target --branch B [--parent P]  the same for a branch with no PR, against P or the default branch
#   github.sh reply N COMMENT_ID FILE     reply to a thread (its first comment's replyTo id)
#   github.sh comment N FILE              a PR comment
#   github.sh resolve THREAD_ID           resolve a review thread
#   github.sh anchors N DRAFTS.json       label each draft's lines changed, context only, or outside the diff
#   github.sh review N SHA DRAFTS.json    post inline comments as one review
#   github.sh approve N SHA [DRAFTS.json] approve the head, with any inline comments, as one review
#   github.sh landed N REVIEW_ID          read back the comments a review posted
#
# DRAFTS.json: [{"path": "src/a.ts", "line": 42, "side": "RIGHT", "body_file": "d1.md"}],
# with optional "start_line" and "start_side" for a range. DRY_RUN=1 prints each write
# instead of sending it.
set -euo pipefail

usage() { grep -v '^# Copy of ' "$0" | sed -n '2,21p' | sed 's/^# \{0,1\}//' >&2; exit 2; }
repo() { gh repo view --json owner,name --jq '.owner.login + "/" + .name'; }
send() {
  if [ "${DRY_RUN:-}" = 1 ]; then printf 'DRY_RUN:'; printf ' %q' "$@"; echo; else "$@"; fi
}

# The review body: the draft comments (none without DRAFTS.json), and `event` when given;
# without one, GitHub creates a pending review.
review_payload() {
  python3 - "$@" <<'PY'
import json, os, sys
sha, drafts_path, event = (sys.argv[1:] + ["", ""])[:3]
comments = []
for draft in json.load(open(drafts_path)) if drafts_path else []:
    comment = {key: draft[key] for key in ("path", "line", "side", "start_line", "start_side") if key in draft}
    comment.setdefault("side", "RIGHT")
    comment["body"] = open(os.path.join(os.path.dirname(os.path.abspath(drafts_path)), draft["body_file"])).read()
    comments.append(comment)
json.dump({"commit_id": sha, "comments": comments, **({"event": event} if event else {})}, sys.stdout)
PY
}

cmd=${1:-}; [ -n "$cmd" ] || usage; shift
case "$cmd" in
  threads)
    [ $# = 1 ] || usage
    slug=$(repo)
    # A thread's first comment is the reply target; `truncated` means more than 100
    # comments, so fetch the rest before judging whether it's answered.
    gh api graphql --paginate -f owner="${slug%/*}" -f repo="${slug#*/}" -F number="$1" -f query='
query($owner:String!,$repo:String!,$number:Int!,$endCursor:String){repository(owner:$owner,name:$repo){pullRequest(number:$number){
  reviewThreads(first:50, after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated path line originalLine
    comments(first:100){totalCount nodes{fullDatabaseId author{login} body url createdAt}}}}}}}' \
      --jq '.data.repository.pullRequest.reviewThreads.nodes[] | {id, isResolved, isOutdated, path, line, originalLine,
        replyTo: .comments.nodes[0].fullDatabaseId, lastAuthor: .comments.nodes[-1].author.login,
        truncated: (.comments.totalCount > (.comments.nodes | length)),
        comments: [.comments.nodes[] | {author: .author.login, body, url, createdAt}]}'
    ;;
  feedback)
    [ $# = 1 ] || usage
    gh pr view "$1" --json reviews,comments \
      --jq '{reviews: [.reviews[] | {author: .author.login, state, body}], comments: [.comments[] | {author: .author.login, body, url}]}'
    # gh pr checks exits 1 when checks fail and 8 while pending; that's their state, not an error.
    status=0; gh pr checks "$1" || status=$?
    echo "checks exit $status (0 passing, 1 failing, 8 pending)"
    # A host can report a build it skipped as passing, such as Vercel's "Canceled by Ignored Build Step".
    gh pr checks "$1" --json name,bucket,description --jq '.[] | select(.bucket == "pass" and
      ((.description // "") | test("^(cancell?ed|skipped)\\b"; "i"))) | "not run: \(.name) (\(.description))"' || true
    "$0" required "$1"
    ;;
  required)
    [ $# = 1 ] || usage
    slug=$(repo)
    read -r base draft <<< "$(gh pr view "$1" --json baseRefName,isDraft --jq '"\(.baseRefName) \(.isDraft)"')"
    # `gh pr checks --required` leaves out required checks that haven't reported yet, so
    # read the contexts from the base branch's rulesets and classic branch protection.
    # A private repo without GitHub Pro can't read rulesets and answers 403 with an
    # upgrade message, which means no required checks from them. Any other 403, such as
    # a rate limit, is an error.
    err=$(mktemp)
    if ! rules=$(gh api "repos/$slug/rules/branches/$base" 2>"$err" \
      --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context'); then
      if ! grep -q 'Upgrade to GitHub Pro.*(HTTP 403)' "$err"; then
        cat "$err" >&2; rm -f "$err"; exit 1
      fi
      rules=""
    fi
    rm -f "$err"
    # An unprotected branch answers 404, with the error body on stdout.
    classic=$(gh api "repos/$slug/branches/$base/protection/required_status_checks" \
      --jq '.contexts[]' 2>/dev/null) || classic=""
    contexts=$(printf '%s\n%s\n' "$rules" "$classic" | sed '/^$/d' | sort -u)
    checks=$(gh pr checks "$1" --json name,bucket --jq '.[] | "\(.name)\t\(.bucket)"' || true)
    # A check can run more than once (a cancelled duplicate); its best state counts. The
    # required contexts count, or every reported check when the base requires none; one
    # that failed, was cancelled, or is running shows CI ran.
    pending=0 ran=0
    counted=${contexts:-$(printf '%s\n' "$checks" | cut -f1 | sort -u)}
    while IFS= read -r context; do
      [ -n "$context" ] || continue
      state=$(printf '%s\n' "$checks" | awk -F'\t' -v name="$context" '$1 == name { seen[$2] = 1 }
        END { split("pass skipping pending fail cancel", order, " ")
              for (i = 1; i <= 5; i++) if (order[i] in seen) { print order[i]; exit }
              print "not reported" }')
      case $state in pending|fail|cancel) ran=1 ;; esac
      [ -n "$contexts" ] || continue
      printf '%s\t%s\n' "$context" "$state"
      case $state in pass|skipping) ;; *) pending=1 ;; esac
    done <<< "$counted"
    [ -n "$contexts" ] || echo "no required checks on $base"
    # A workflow that reads `pull_request.draft` usually skips its jobs on a draft while
    # their aggregate checks pass, so green there can mean no CI ran. A skipped check on
    # the head shows it did skip: a draft whose CI ran before it went back to draft has
    # none. The workflows come from the base tip on GitHub, so any checkout works unfetched.
    skips=""
    if [ "$draft" = true ] && printf '%s\n' "$checks" | cut -f2 | grep -qx skipping; then
      skips=$(gh api graphql -f owner="${slug%/*}" -f repo="${slug#*/}" -f expression="$base:.github/workflows" -f query='
query($owner:String!,$repo:String!,$expression:String!){repository(owner:$owner,name:$repo){
  object(expression:$expression){... on Tree{entries{name object{... on Blob{text}}}}}}}' \
        --jq '(.data.repository.object.entries // [])[] | select((.object.text // "") | contains("pull_request.draft")) | .name' \
        | paste -sd ' ' -)
    fi
    if [ -n "$skips" ]; then echo "workflows that skip drafts: $skips"; fi
    if [ -n "$skips" ] && [ "$ran" = 0 ]; then
      echo "required: not run (draft; CI skips drafts here)"
    else
      echo "required: $([ "$pending" = 0 ] && echo "all passed" || echo "not all passed")"
    fi
    ;;
  mergeable)
    [ $# = 1 ] || usage
    # GitHub's own verdict, not one rebuilt from check states: a label event can re-run CI
    # with skipped required jobs and block the merge while every check looks green.
    # UNKNOWN means GitHub is still computing it; read it again.
    read -r state draft merge_state head <<< "$(gh pr view "$1" --json state,isDraft,mergeStateStatus,headRefOid \
      --jq '"\(.state) \(.isDraft) \(.mergeStateStatus) \(.headRefOid)"')"
    echo "head $head"
    echo "state $state · draft $draft · merge state $merge_state"
    "$0" required "$1" || true
    if [ "$state" != OPEN ]; then echo "mergeable: no ($(printf %s "$state" | tr "[:upper:]" "[:lower:]"))"; exit 1; fi
    if [ "$draft" = true ]; then echo "mergeable: no (draft; merge state once ready: $merge_state)"; exit 1; fi
    case $merge_state in
      CLEAN|HAS_HOOKS) echo "mergeable: yes" ;;
      UNKNOWN) echo "mergeable: unknown (GitHub is still computing it)"; exit 8 ;;
      DRAFT) echo "mergeable: no (draft)"; exit 1 ;;
      BLOCKED) echo "mergeable: no (blocked: a required check, review, or rule)"; exit 1 ;;
      BEHIND) echo "mergeable: no (behind its base)"; exit 1 ;;
      DIRTY) echo "mergeable: no (conflicts)"; exit 1 ;;
      UNSTABLE) echo "mergeable: no (a non-required check fails)"; exit 1 ;;
      *) echo "mergeable: no ($merge_state)"; exit 1 ;;
    esac
    ;;
  head)
    [ $# = 1 ] || usage
    gh pr view "$1" --json headRefOid --jq .headRefOid
    ;;
  target)
    if [ "${1:-}" = --branch ]; then
      [ $# = 2 ] || { [ $# = 4 ] && [ "$3" = --parent ]; } || usage
      n=none branch=$2 base=${4:-}
      [ -n "$base" ] || base=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
      # A branch's tip: origin's when the local branch is behind it or missing, else the
      # local one, which a stack's unpushed layers and a diverged branch keep.
      tip() {
        git fetch --quiet --no-tags origin "$1" 2>/dev/null || true
        local mine theirs
        mine=$(git rev-parse --verify --quiet "refs/heads/$1^{commit}") || true
        theirs=$(git rev-parse --verify --quiet "refs/remotes/origin/$1^{commit}") || true
        if [ -n "$mine" ] && { [ -z "$theirs" ] || ! git merge-base --is-ancestor "$mine" "$theirs"; }; then
          echo "$mine"
        elif [ -n "$theirs" ]; then
          echo "$theirs"
        else
          echo "no branch $1 here or on origin" >&2; return 1
        fi
      }
      base_sha=$(tip "$base")
      head_sha=$(tip "$branch")
    else
      [ $# -le 1 ] || usage
      pr=$(gh pr view ${1:+"$1"} --json number,baseRefName,baseRefOid,headRefOid,headRefName \
        --jq '"\(.number) \(.baseRefName) \(.baseRefOid) \(.headRefOid) \(.headRefName)"')
      read -r n base base_sha head_sha branch <<< "$pr"
      # Fetch as merge-gate.py does, so both SHAs exist locally and the diff matches its own.
      git fetch --quiet --no-tags origin "$base" "pull/$n/head"
    fi
    local_head=$(git rev-parse HEAD)
    [ "$local_head" = "$head_sha" ] && match=matches || match=differs
    [ -z "$(git status --porcelain --untracked-files=no)" ] && clean=yes || clean=no
    printf 'pr: %s\nbranch: %s\nbase: %s\nbase_sha: %s\nhead_sha: %s\nlocal_head: %s (%s)\nclean: %s\n' \
      "$n" "$branch" "$base" "$base_sha" "$head_sha" "$match" "$local_head" "$clean"
    # A skill bundles verdicts.py beside this script; the repo keeps it in hooks/.
    verdicts="$(dirname "$0")/verdicts.py"
    [ -f "$verdicts" ] || verdicts="$(dirname "$(realpath "$0")")/../../skills/primitive/addystack/hooks/verdicts.py"
    python3 "$verdicts" status "$base_sha" "$head_sha"
    # The branch's last verdict, for verify-work's quick re-check, and whether a re-check can
    # change it, read only in a clean checkout at head_sha: a checkout past it holds commits
    # no verdict saw, and uncommitted changes would be what its checks run.
    if [ "$match" = matches ] && [ "$clean" = yes ]; then
      python3 "$verdicts" last "$branch" "$base_sha" "$head_sha"
    else
      python3 "$verdicts" last "$branch"
    fi
    ;;
  reply)
    [ $# = 3 ] || usage
    send gh api --method POST "repos/$(repo)/pulls/$1/comments/$2/replies" -F body=@"$3" --jq .html_url
    ;;
  comment)
    [ $# = 2 ] || usage
    send gh pr comment "$1" --body-file "$2"
    ;;
  resolve)
    [ $# = 1 ] || usage
    send gh api graphql -f threadId="$1" \
      -f query='mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{isResolved}}}'
    ;;
  anchors)
    [ $# = 2 ] || usage
    files=$(mktemp)
    gh api --paginate "repos/$(repo)/pulls/$1/files" --jq '.[] | {filename, patch}' > "$files"
    # GitHub accepts a comment on any line a hunk shows, context lines included, so "in the
    # diff" doesn't mean "written by this PR". Exits 1 when a line is outside the diff.
    python3 - "$files" "$2" <<'PY'
import json, re, sys
files_path, drafts_path = sys.argv[1:]
labels = {}
for raw in open(files_path):
    file = json.loads(raw)
    right, left, old, new = {}, {}, 0, 0
    for row in (file.get("patch") or "").split("\n"):
        hunk = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", row)
        if hunk:
            old, new = int(hunk[1]), int(hunk[2])
        elif row.startswith("+"):
            right[new] = "added"; new += 1
        elif row.startswith("-"):
            left[old] = "deleted"; old += 1
        elif not row.startswith("\\"):
            right[new] = left[old] = "context"; old += 1; new += 1
    labels[file["filename"], "RIGHT"], labels[file["filename"], "LEFT"] = right, left
outside = False
for draft in json.load(open(drafts_path)):
    side, end = draft.get("side", "RIGHT"), draft["line"]
    start, start_side = draft.get("start_line", end), draft.get("start_side", side)
    span = range(start, end + 1) if start_side == side else [start, end]
    sides = [side] * len(span) if start_side == side else [start_side, side]
    found = [labels.get((draft["path"], s), {}).get(n) for n, s in zip(span, sides)]
    missing = [n for n, label in zip(span, found) if label is None]
    if missing:
        outside = True
        verdict = f"outside the diff at line {missing[0]}"
    elif all(label == "context" for label in found):
        verdict = "context only: the PR didn't write these lines"
    else:
        verdict = "changed"
    print(f"{draft['path']}:{start}-{end} {side}\t{verdict}")
sys.exit(1 if outside else 0)
PY
    ;;
  review)
    [ $# = 3 ] || usage
    "$0" anchors "$1" "$3"
    slug=$(repo); payload=$(mktemp)
    review_payload "$2" "$3" > "$payload"
    if [ "${DRY_RUN:-}" = 1 ]; then
      echo "DRY_RUN: create a pending review on $slug#$1, then submit it with event=COMMENT:"
      cat "$payload"; echo; exit 0
    fi
    # Leaving out `event` creates a pending review; submitting it with COMMENT and no
    # body posts only the inline comments.
    if ! id=$(gh api --method POST "repos/$slug/pulls/$1/reviews" --input "$payload" --jq .id); then
      echo "creating the review failed; an existing pending review blocks a new one:" >&2
      gh api "repos/$slug/pulls/$1/reviews" --jq '.[] | select(.state == "PENDING") | {id, user: .user.login}' >&2
      echo "show it to the user, who decides what happens to it" >&2
      exit 1
    fi
    gh api --method POST "repos/$slug/pulls/$1/reviews/$id/events" -f event=COMMENT --jq .html_url
    ;;
  approve)
    [ $# = 2 ] || [ $# = 3 ] || usage
    head=$("$0" head "$1")
    if [ "$head" != "$2" ]; then
      echo "the head moved from $2 to $head; re-check the review against it before approving" >&2
      exit 1
    fi
    [ $# = 2 ] || "$0" anchors "$1" "$3"
    slug=$(repo); payload=$(mktemp)
    review_payload "$2" "${3:-}" APPROVE > "$payload"
    if [ "${DRY_RUN:-}" = 1 ]; then
      echo "DRY_RUN: approve $slug#$1 at $2:"; cat "$payload"; echo; exit 0
    fi
    gh api --method POST "repos/$slug/pulls/$1/reviews" --input "$payload" --jq .html_url
    ;;
  landed)
    [ $# = 2 ] || usage
    # The review's own comments endpoint returns line: null; the PR's comments carry the anchor.
    gh api --paginate "repos/$(repo)/pulls/$1/comments" \
      --jq ".[] | select(.pull_request_review_id == $2) | {path, start_line, line, original_line, side, commit_id, html_url}"
    ;;
  *) usage ;;
esac

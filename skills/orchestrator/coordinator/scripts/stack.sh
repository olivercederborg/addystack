#!/usr/bin/env bash
# Copy of shared/scripts/stack.sh, written by scripts/sync-copies.py: edit the source, then run the script.
# gh stack state, start, where, and restack, with the preconditions gh stack fails on
# checked first. Run it inside the repo; it prints plain lines.
#
#   stack.sh state                    branch (or detached, and which branch's tip HEAD is), its
#                                     stack and layers, uncommitted changes, a rebase in progress
#   stack.sh where <branch|#PR>       the checkout that can merge the PR and the merge line to run
#                                     there; it never runs the merge, so the merge gate still sees it
#   stack.sh start <branch> [--base B]  a new stack on origin/B (default: origin's default branch),
#                                     from a detached or unstacked checkout; refuses on a stacked one
#   stack.sh restack [--upstack]      gh stack rebase, continuing each stop git leaves no unmerged
#                                     paths at (a rerere resolution); exit 3 lists the conflicted files
#
# Exits 0 when done, 1 when gh stack or git refuses (its message is printed), 2 on usage,
# and 3 when restack stops at a conflict.
set -euo pipefail

usage() { grep -v '^# Copy of ' "$0" | sed -n '2,15p' | sed 's/^# \{0,1\}//' >&2; exit 2; }
repo() { gh repo view --json owner,name --jq '.owner.login + "/" + .name'; }

# Worktrees as "path<TAB>branch", with an empty branch for a detached one.
worktrees() {
  git worktree list --porcelain | awk '
    /^worktree / { if (path != "") print path "\t" branch; path = substr($0, 10); branch = "" }
    /^branch refs\/heads\// { branch = substr($0, 19) }
    END { if (path != "") print path "\t" branch }'
}

# Where gh stack's own rebase stopped, from the record it keeps for `--continue`, as
# "checkout<TAB>stack branches": the checkout holding the branch it stopped on. Nothing
# when none is stopped. A rebase another checkout runs with plain git isn't this one.
stopped() {
  local record
  record="$(git rev-parse --path-format=absolute --git-common-dir)/gh-stack-rebase-state"
  [ -f "$record" ] || return 0
  python3 -c '
import json, sys
state = json.load(open(sys.argv[1]))
places = state.get("worktrees") or {}
owner = (places.get("owners") or {}).get(state.get("conflictBranch")) or places.get("origin") or {}
print(owner.get("path") or sys.argv[2], " ".join(state.get("stackBranches") or []), sep="\t")' \
    "$record" "$(git rev-parse --show-toplevel)" 2>/dev/null || printf '%s\t\n' "$(git rev-parse --show-toplevel)"
}

# Each unmerged path in the checkout $1, as "checkout: file".
conflicts() {
  local file
  git -C "$1" diff --name-only --diff-filter=U | while IFS= read -r file; do printf '%s: %s\n' "$1" "$file"; done
}

# The stack from `gh stack view --json` in $1: "trunk <name>", then one line per layer,
# bottom first: "  branch #PR STATE[  needs rebase][  ← current]".
layers() {
  (cd "$1" && gh stack view --json) | python3 -c '
import json, sys
stack = json.load(sys.stdin)
print("trunk", stack["trunk"])
for b in stack["branches"]:
    pr = b.get("pr") or {}
    words = [" ", b["name"]] + (["#%s" % pr["number"]] if pr else [])
    words.append("MERGED" if b.get("isMerged") else pr.get("state", "no PR"))
    words += [" needs rebase"] if b.get("needsRebase") else []
    words += [" ← current"] if b.get("isCurrent") else []
    print(" ".join(words))'
}

# Whether `gh stack view --json` in $1, which the merge gate reads, can merge PR $2 as
# GitHub will: it lists #$2 as open and holds each of the stack's branches ($3…), since
# GitHub merges every layer below #$2 and the gate checks only the ones it lists.
# Prints what's wrong when it can't.
local_stack() {
  local view
  if ! view=$(cd "$1" && gh stack view --json 2>&1); then
    echo "gh stack view in $1 fails: ${view%%$'\n'*}"; return 1
  fi
  printf '%s' "$view" | python3 -c '
import json, sys
n, path, github = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
branches = json.load(sys.stdin)["branches"]
if not any((b.get("pr") or {}).get("number") == n and not b.get("isMerged") for b in branches):
    sys.exit(f"gh stack view in {path} does not list #{n} as open")
missing = " ".join(b for b in github if b not in {b["name"] for b in branches})
if missing:
    sys.exit(f"GitHub stack has {missing}, which the stack in {path} lacks; run gh stack sync there")
' "$2" "$1" "${@:3}" 2>&1
}

# A PR's GitHub stack: "number state draft branch stack-number|none merge-method entry-branches…",
# where merge-method is the one GitHub preselects for this user (their last one).
# gh stack merge takes only a PR GitHub has in a stack (one of two or more PRs), so a lone
# PR merges with gh pr merge.
pull() {
  local slug; slug=$(repo)
  gh api graphql -f owner="${slug%/*}" -f name="${slug#*/}" -F n="$1" -f query='
query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){
  viewerDefaultMergeMethod
  pullRequest(number:$n){number state isDraft headRefName
    stack{number entries(first:100){nodes{pullRequest{headRefName}}}}}}}' \
    --jq '.data.repository | [.pullRequest.number, .pullRequest.state, .pullRequest.isDraft,
      .pullRequest.headRefName, (.pullRequest.stack.number // "none"),
      (.viewerDefaultMergeMethod | ascii_downcase),
      (.pullRequest.stack.entries.nodes // [] | map(.pullRequest.headRefName))[]] | map(tostring) | join(" ")'
}

cmd_state() {
  local branch tips view err
  # `needs rebase` compares against the fetched trunk.
  git fetch --quiet --no-tags origin 2>/dev/null || echo "fetch: failed, so needs rebase may be stale"
  branch=$(git branch --show-current)
  if [ -n "$branch" ]; then
    echo "branch: $branch"
  else
    tips=$(git for-each-ref --points-at HEAD --format='%(refname:short)' refs/heads | paste -sd ' ' -)
    echo "branch: detached at $(git rev-parse --short HEAD) (tip of: ${tips:-no local branch})"
  fi
  err=$(mktemp)
  if view=$(layers . 2>"$err"); then
    local first number=""
    first=$(printf '%s\n' "$view" | grep -o ' #[0-9]*' | head -1 | tr -d ' #') || true
    # Informational: a failed lookup here mustn't fail the start or restack before it.
    [ -z "$first" ] || number=$(pull "$first" | cut -d' ' -f5) || number="unknown (GitHub lookup failed)"
    case $number in
      ""|none) number="local only" ;;
      [0-9]*) number="#$number" ;;
    esac
    echo "stack: $number, on ${view%%$'\n'*}" | sed 's/on trunk /on /'
    printf '%s\n' "$view" | sed 1d
  else
    echo "stack: none ($(head -1 "$err"))"
  fi
  rm -f "$err"
  echo "changes: $(git status --porcelain --untracked-files=no | wc -l | tr -d ' ') tracked files," \
    "$(git ls-files --others --exclude-standard | wc -l | tr -d ' ') untracked"
  local record; record=$(stopped)
  if [ -n "$record" ]; then echo "rebase: stopped in ${record%%$'\t'*} (stack.sh restack continues it)"; else echo "rebase: none"; fi
}

cmd_where() {
  [ $# = 1 ] || usage
  local target=${1#\#} n fields state draft branch stack method path="" holder wt_branch quoted problem
  if [[ $target =~ ^[0-9]+$ ]]; then
    n=$target
  elif ! n=$(gh pr view "$target" --json number --jq .number 2>/dev/null); then
    echo "pr: none for branch $target"; exit 1
  fi
  fields=$(pull "$n")
  read -r n state draft branch stack method entries <<< "$fields"
  echo "pr: #$n ($state$([ "$draft" = true ] && echo ", draft"))"
  echo "branch: $branch"
  # The PR's own checkout first, else one holding another layer of its stack: the gate
  # reads the stack from `gh stack view --json` in the merge's directory.
  while IFS=$'\t' read -r holder wt_branch; do
    if [ "$wt_branch" = "$branch" ]; then path=$holder; break; fi
    if [ -z "$path" ] && [ "$stack" != none ] && [[ " $entries " == *" $wt_branch "* ]]; then path=$holder; fi
  done < <(worktrees)
  echo "worktree: ${path:-none}"
  echo "stack: $([ "$stack" = none ] && echo "none (GitHub has no stack with this PR)" || echo "#$stack")"
  if [ "$state" != OPEN ]; then echo "merge: none ($state)"; exit 1; fi
  if [ "$stack" = none ]; then
    printf -v quoted %q "$(git rev-parse --show-toplevel)"
    echo "merge: cd $quoted && gh pr merge $n --$method"
    exit 0
  fi
  if [ -z "$path" ]; then
    echo "merge: none: no checkout holds $branch; add one (git worktree add <dir> $branch) and run where again"
    exit 1
  fi
  if ! problem=$(local_stack "$path" "$n" $entries); then
    echo "merge: none: $problem"
    exit 1
  fi
  printf -v quoted %q "$path"
  echo "merge: cd $quoted && gh stack merge $n --yes"
}

cmd_start() {
  local branch="" base="" current view
  while [ $# -gt 0 ]; do
    case $1 in
      --base) [ $# -ge 2 ] || usage; base=$2; shift 2 ;;
      -*) usage ;;
      *) [ -z "$branch" ] || usage; branch=$1; shift ;;
    esac
  done
  [ -n "$branch" ] || usage
  [ -n "$base" ] || base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || true
  base=${base#origin/}
  [ -n "$base" ] || base=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
  current=$(git branch --show-current)
  # A trunk starts stacks of its own; a branch in a stack takes a layer instead.
  if [ -n "$current" ] && view=$(gh stack view --json 2>/dev/null) && printf '%s' "$view" |
    python3 -c 'import json, sys; sys.exit(sys.argv[1] not in [b["name"] for b in json.load(sys.stdin)["branches"]])' "$current"; then
    echo "$current is already in a stack; add a layer with gh stack add, or start from a detached checkout:"
    layers . | sed 1d
    exit 1
  fi
  git fetch --quiet --no-tags origin "$base"
  if [ "$current" = "$branch" ]; then
    # Stacking the checked-out branch keeps its commits.
    [ "$(git rev-list --count "HEAD..origin/$base")" = 0 ] || echo "$branch is behind origin/$base; run stack.sh restack after this"
  elif ! git show-ref --quiet --verify "refs/heads/$branch"; then
    git switch --quiet --no-track -c "$branch" "origin/$base"
  elif [ "$(git rev-list --count "origin/$base..$branch")" = 0 ]; then
    # A failed `gh stack init` from a detached checkout still made the branch, with nothing on it.
    git switch --quiet --no-track -C "$branch" "origin/$base"
  else
    echo "$branch already exists with commits not on origin/$base; pick another name, or check it out and run start there" >&2
    exit 1
  fi
  gh stack init --base "$base" "$branch"
  cmd_state
}

cmd_restack() {
  local args=() status record path branches current before=""
  while [ $# -gt 0 ]; do
    case $1 in --upstack) args+=(--upstack); shift ;; *) usage ;; esac
  done
  # A rerun after resolving continues the stopped rebase; starting another one exits 7.
  record=$(stopped)
  if [ -n "$record" ]; then
    IFS=$'\t' read -r path branches <<< "$record"
    current=$(git branch --show-current)
    if [ "$(git rev-parse --show-toplevel)" != "$path" ] && [[ " $branches " != *" ${current:-(detached)} "* ]]; then
      echo "a gh stack rebase of $branches is stopped in $path; finish it there first" >&2
      exit 1
    fi
    status=1
  else
    status=0; gh stack rebase ${args[@]+"${args[@]}"} || status=$?
  fi
  while [ "$status" != 0 ]; do
    record=$(stopped)
    if [ -z "$record" ]; then
      echo "gh stack rebase failed before any conflict (above); fix what it names and rerun" >&2
      exit 1
    fi
    path=${record%%$'\t'*}
    if [ -n "$(conflicts "$path")" ]; then
      echo "conflict: resolve each file, git add it in its worktree, and run stack.sh restack again:"
      conflicts "$path"
      exit 3
    fi
    # No unmerged paths: rerere resolved this stop, or the files are resolved and added.
    # A continue that fails and leaves the same stop isn't a conflict to continue past.
    if [ -n "$before" ] && [ "$before" = "$record $(git -C "$path" rev-parse -q --verify REBASE_HEAD)" ]; then
      echo "gh stack rebase --continue failed without moving on (above); fix what it names and rerun" >&2
      exit 1
    fi
    before="$record $(git -C "$path" rev-parse -q --verify REBASE_HEAD)"
    status=0; GIT_EDITOR=true gh stack rebase --continue || status=$?
  done
  cmd_state
}

cmd=${1:-}; [ -n "$cmd" ] || usage; shift
case "$cmd" in
  state) [ $# = 0 ] || usage; cmd_state ;;
  where) cmd_where "$@" ;;
  start) cmd_start "$@" ;;
  restack) cmd_restack "$@" ;;
  *) usage ;;
esac

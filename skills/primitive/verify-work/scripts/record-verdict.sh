#!/usr/bin/env bash
# Records a verdict; runs only in a fresh work-verifier. See hooks/verdicts.py.
# Usage: record-verdict.sh <base-sha> <reviewed-head> [--verdict done|not-done|not-verified]
#          [--evidence KIND=REF]... [--require KIND]... [--finding TEXT]... [--branch B]
# The verdict defaults to done; not-done and not-verified need at least one --finding.
# Done needs evidence for each kind the diff's type (`verdicts.py classify`) or --require
# asks for; see verify-work/references/evidence.md.
# Run it from any checkout of the repo: when HEAD isn't the reviewed head on the --branch
# given, it records from a temporary worktree at that head and removes it on exit. The
# branch is then --branch, or the one local (else origin) branch whose tip is the head.
set -euo pipefail
# The copy of hooks/verdicts.py beside this script, which an installed skill also holds.
verdicts="$(dirname "$(realpath "$0")")/verdicts.py"
head=$(git rev-parse --verify --quiet "${2:-}^{commit}" 2>/dev/null) || exec python3 "$verdicts" record "$@"
named='' previous=''
for arg in "$@"; do
  case $arg in --branch=*) named=${arg#--branch=} ;; esac
  [ "$previous" != --branch ] || named=$arg
  previous=$arg
done
# In place only when HEAD is the head on the branch the verdict names, if it names one.
if [ "$(git rev-parse HEAD)" = "$head" ] && { [ -z "$named" ] || [ "$(git branch --show-current)" = "$named" ]; }; then
  exec python3 "$verdicts" record "$@"
fi

args=("$@")
if [ -z "$named" ]; then
  for refs in refs/heads refs/remotes/origin; do
    branch=$(git for-each-ref --points-at "$head" --format='%(refname)' "$refs" | grep -v '/HEAD$' || true)
    if [ -n "$branch" ]; then
      [[ $branch == *$'\n'* ]] || args+=(--branch "${branch#"$refs"/}")
      break
    fi
  done
fi

worktree=$(mktemp -d "${TMPDIR:-/tmp}/record-verdict.XXXXXX")
cleanup() { git worktree remove --force "$worktree" 2>/dev/null || { rm -rf "$worktree"; git worktree prune; }; }
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
git worktree add --quiet --detach "$worktree" "$head"
# Git runs in the worktree, so HEAD is the reviewed head; evidence paths still resolve
# against this directory.
status=0
GIT_DIR=$(git -C "$worktree" rev-parse --absolute-git-dir) GIT_WORK_TREE="$worktree" \
  python3 "$verdicts" record "${args[@]}" || status=$?
exit "$status"

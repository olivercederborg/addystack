#!/usr/bin/env bash
# Writes review-loop's packet and the one prompt every reviewer gets, under the repo's
# .review-loop/, then prints both paths and the loop's baseline (`git diff --shortstat`
# over the diff the packet holds).
#
#   packet.sh pr N [OPTIONS]              the PR diff, fetched as the merge gate does, at the
#                                         local branch instead when it's ahead (unpushed fixes)
#   packet.sh range BASE..HEAD [OPTIONS]  `git diff BASE...HEAD`; a branch is PARENT..BRANCH
#   packet.sh working [--base REV] [OPTIONS]  staged, unstaged, and untracked changes against
#                                         REV (default HEAD; round 1's base once fixes commit)
#   packet.sh plan FILE [OPTIONS]         a plan or design, in place of a diff
#   packet.sh clean                       removes .review-loop/ when the loop ends
#
# OPTIONS: --checks FILE (each check already run, one `command → result` line), --intent
# FILE (the user's plan or stated intent), --only PATH (review only this file or folder;
# repeatable), --keep PATH (keep a file the packet leaves out; repeatable), and from
# round 2 --round N --previous FILE (the findings and their fixes) --settled FILE (every
# dropped, skipped, or follow-up finding, each with why). PATHs are from the repo root.
# Left out unless kept: lockfiles, binaries, and vendored or generated files (by path,
# or by the linguist-vendored and linguist-generated attributes).
set -euo pipefail

self=$(realpath "$0")  # before the cd below, since $0 may be relative
usage() { sed -n '2,21p' "$self" | sed 's/^# \{0,1\}//' >&2; exit 2; }
root=$(git rev-parse --show-toplevel)
cmd=${1:-}; [ -n "$cmd" ] || usage; shift
case $cmd in
  clean) [ $# = 0 ] || usage; rm -rf "$root/.review-loop"; exit 0 ;;
  pr | range | plan) [ $# -ge 1 ] || usage; arg=$1; shift ;;
  working) arg= ;;
  *) usage ;;
esac
checks='' intent='' round=1 previous='' settled='' keep=() only=() since=HEAD
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case $1 in
    --checks) checks=$2 ;;
    --intent) intent=$2 ;;
    --round) round=$2 ;;
    --previous) previous=$2 ;;
    --settled) settled=$2 ;;
    --keep) keep+=("$2") ;;
    --only) only+=("$2") ;;
    --base) [ "$cmd" = working ] || usage; since=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ $round =~ ^[1-9][0-9]*$ ]] || usage
if [ "$round" -gt 1 ] && { [ -z "$previous" ] || [ -z "$settled" ]; }; then
  echo "round $round needs --previous and --settled" >&2; exit 2
fi
plan=''; [ "$cmd" != plan ] || plan=$arg
for file in "$checks" "$intent" "$previous" "$settled" "$plan"; do
  [ -z "$file" ] || [ -f "$file" ] || { echo "no such file: $file" >&2; exit 2; }
done
# Git prints paths from the root, so run there, with the files given from here.
absolute() { [ -z "$1" ] || case $1 in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac; }
checks=$(absolute "$checks") intent=$(absolute "$intent") previous=$(absolute "$previous")
settled=$(absolute "$settled") plan=$(absolute "$plan")
cd "$root"

# Reviewers read the packet inside the repo, so git must never see it.
exclude=$(git rev-parse --git-path info/exclude)
mkdir -p "$(dirname "$exclude")"
grep -qxF /.review-loop/ "$exclude" 2>/dev/null || echo /.review-loop/ >> "$exclude"

join() {
  [ $# -gt 0 ] || { echo nothing; return; }
  printf '%s' "$1"; shift
  [ $# = 0 ] || printf ', %s' "$@"
  echo
}
sections=()
case $cmd in
  pr)
    IFS=$'\t' read -r base_ref base head head_ref url < <(gh pr view "$arg" \
      --json baseRefName,baseRefOid,headRefOid,headRefName,url \
      --jq '[.baseRefName, .baseRefOid, .headRefOid, .headRefName, .url] | @tsv')
    [ -n "${url:-}" ] || exit 1
    git fetch --quiet --no-tags origin "$base_ref" "pull/$arg/head"
    target="PR #$arg ($url)"
    # A later round reviews the fixes the loop commits before it pushes.
    if mine=$(git rev-parse --verify --quiet "refs/heads/$head_ref^{commit}") && [ "$mine" != "$head" ] &&
      git merge-base --is-ancestor "$head" "$mine"; then
      head=$mine target="$target at local $head_ref, ahead of the PR"
    fi
    spec=("$base...$head") id=${head:0:12}
    ;;
  range)
    [[ $arg == *..* ]] || usage
    base=$(git rev-parse --verify "${arg%%..*}^{commit}")
    head=$(git rev-parse --verify "${arg##*..}^{commit}")
    target="range $arg" spec=("$base...$head") id=${head:0:12}
    ;;
  working)
    base=$(git rev-parse --verify "$since^{commit}") head="the working tree"
    # Intent-to-add, so the diff and its shortstat count untracked files, in a copy of
    # the index: the user's index never changes, so clean has nothing to undo.
    mkdir -p "$root/.review-loop"
    index=$(git rev-parse --git-path index)
    export GIT_INDEX_FILE="$root/.review-loop/index"
    rm -f "$GIT_INDEX_FILE"
    [ ! -f "$index" ] || cp "$index" "$GIT_INDEX_FILE"
    git ls-files -z --others --exclude-standard -- ${only[@]+"${only[@]}"} | xargs -0 -r git add -N --
    target="working changes" spec=("$base") id=working-${base:0:12}
    ;;
  plan)
    base='' head='' target="plan $arg" spec=() id=plan-$(git hash-object "$plan" | cut -c1-12)
    ;;
esac
dir="$root/.review-loop/$id"
mkdir -p "$dir"
packet="$dir/packet.md" prompt="$dir/prompt.md"

kept=() left=()
if [ "$cmd" != plan ]; then
  while IFS=$'\t' read -r -d '' insertions _ path; do
    if [ ${#only[@]} -gt 0 ]; then
      inside=no
      for scope in "${only[@]}"; do case $path in "${scope%/}" | "${scope%/}"/*) inside=yes ;; esac; done
      [ "$inside" = yes ] || continue
    fi
    why=''
    case "/$path" in
      */package-lock.json | */npm-shrinkwrap.json | */yarn.lock | */pnpm-lock.yaml | */bun.lock | */bun.lockb | \
        */Cargo.lock | */Gemfile.lock | */poetry.lock | */uv.lock | */Pipfile.lock | */composer.lock | \
        */go.sum | */Podfile.lock | */Package.resolved | */flake.lock) why=lockfile ;;
      */vendor/* | */node_modules/* | */third_party/*) why=vendored ;;
      *.min.js | *.min.css | *.map | *.pb.go | *_pb2.py | *.generated.*) why=generated ;;
    esac
    [ "$insertions" != - ] || why=binary
    if [ -z "$why" ]; then
      case $(git check-attr linguist-vendored linguist-generated -- "$path") in
        *"linguist-vendored: set"* | *"linguist-vendored: true"*) why=vendored ;;
        *"linguist-generated: set"* | *"linguist-generated: true"*) why=generated ;;
      esac
    fi
    for path_kept in ${keep[@]+"${keep[@]}"}; do [ "$path_kept" != "$path" ] || why=; done
    if [ -z "$why" ]; then kept+=("$path"); else left+=("$path ($why)"); fi
  done < <(git diff --numstat -z --no-renames "${spec[@]}")
fi

kept_diff() { [ ${#kept[@]} = 0 ] || git diff --no-color --no-ext-diff --no-renames "$@" "${spec[@]}" -- "${kept[@]}"; }
{
  echo "# Review packet"
  echo
  echo "Target: $target"
  [ -z "$base" ] || printf 'Base: %s\nHead: %s\n' "$base" "$head"
  if [ "$cmd" = plan ]; then
    printf '\n## Plan\n\n'; cat "$plan"
  else
    printf '\n## Files\n\n'
    kept_diff --numstat | awk -F'\t' '{ print "- " $3 " (+" $1 " -" $2 ")" }'
    printf '\nLeft out: %s\n' "$(join ${left[@]+"${left[@]}"})"
  fi
  if [ "$cmd" = pr ]; then
    sections+=("PR description")
    printf '\n## PR description\n\n'
    gh pr view "$arg" --json title,body --jq '"# " + .title + "\n\n" + .body'
    issues=$(gh pr view "$arg" --json closingIssuesReferences --jq '.closingIssuesReferences[].url')
    if [ -n "$issues" ]; then
      sections+=("Linked issues")
      printf '\n## Linked issues\n'
      for issue in $issues; do
        printf '\n'; gh issue view "$issue" --json title,body,url --jq '"### " + .title + " (" + .url + ")\n\n" + .body'
      done
    fi
  fi
  if [ -n "$intent" ]; then
    sections+=(Intent)
    printf '\n## Intent\n\n'; cat "$intent"
  fi
  if [ "$cmd" != plan ]; then
    printf '\n## Diff\n\n'; kept_diff
  fi
} > "$packet"

if [ "$cmd" = plan ]; then
  kind=plan scope="the plan in the packet" baseline="none (a plan has no size)"
  ask="Report every gap, risk, and simpler option with a severity, the part of the plan it concerns, what goes wrong, and the smallest change to the plan that covers it:"
else
  kind=change scope="the files under Files in the packet; left out: $(sed -n 's/^Left out: //p' "$packet")"
  baseline=$(kept_diff --shortstat | sed 's/^ *//') baseline=${baseline:-0 files changed}
  ask="Report every finding with a severity, a file:line, the failure it causes, its class (the kind of mistake, with every other place in the change that makes it), and the smallest fix that covers the whole class:"
fi
spec_line=none; [ ${#sections[@]} = 0 ] || spec_line="the packet's $(join "${sections[@]}") sections"
here=$(dirname "$self")
python3 - "$here/review-prompt.md" "$here/../references/review-lenses.md" "$prompt" "$kind" "$target" "$scope" "$spec_line" \
  "$packet" "$round" "$previous" "$settled" "$checks" "$ask" <<'PY'
import sys
template, lenses, out, kind, target, scope, spec, packet, round_, previous, settled, checks, ask = sys.argv[1:]
read = lambda path: open(path).read().strip()
block = "" if round_ == "1" else (
    f"Round {round_}. Previous findings and their fixes:\n{read(previous)}\nSettled, each with why:\n{read(settled)}\n"
    "Check each fix, then look for regressions and anything new in the updated diff; a settled finding stays settled.\n")
values = {"kind": kind, "target": target, "scope": scope, "spec": spec, "packet": packet, "round": block,
          "checks": read(checks) if checks else "none", "lenses": read(lenses), "ask": ask}
text = read(template) + "\n"
for key, value in values.items():
    text = text.replace("{" + key + "}", value)
open(out, "w").write(text)
PY
printf 'packet: %s\nprompt: %s\nbaseline: %s\n' "$packet" "$prompt" "$baseline"

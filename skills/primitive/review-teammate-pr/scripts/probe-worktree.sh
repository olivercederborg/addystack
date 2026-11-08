#!/usr/bin/env bash
# Copy of shared/scripts/probe-worktree.sh, written by scripts/sync-copies.py: edit the source, then run the script.
# Probe a commit in a throwaway worktree whose workspace packages resolve to that commit.
#
#   probe-worktree.sh create <ref> [--codegen "<cmd>"]   print the new worktree's path
#   probe-worktree.sh tsc <dir> <package-dir> <label>    typecheck, save the error list
#   probe-worktree.sh diff <dir> <label-a> <label-b>     compare two saved error lists
#   probe-worktree.sh remove <dir>                       delete the worktree
#
# Run it from the repo's main checkout. When that checkout has node_modules, `create`
# links each entry, except workspace packages, which it points at the probe tree.
# Linking the whole node_modules folder instead silently typechecks the main
# checkout's packages. `tsc` needs those dependencies installed.
set -euo pipefail

die() { echo "probe-worktree: $*" >&2; exit 1; }

link_entries() {
  # link_entries <source node_modules dir> <target dir> <repo root> <probe dir>
  local src=$1 dst=$2 root=$3 probe=$4 entry name target
  for entry in "$src"/* "$src"/.[!.]*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    name=$(basename "$entry")
    if [[ $name == @* && -d $entry && ! -L $entry ]]; then
      mkdir -p "$dst/$name"
      link_entries "$entry" "$dst/$name" "$root" "$probe"
      continue
    fi
    if [ -L "$entry" ]; then
      target=$(cd "$(dirname "$entry")" && cd "$(dirname "$(readlink "$entry")")" && pwd -P)/$(basename "$(readlink "$entry")")
      if [[ $target == "$root"/* && $target != "$root"/node_modules/* ]]; then
        ln -s "$probe/${target#"$root"/}" "$dst/$name"
        continue
      fi
    fi
    ln -s "$entry" "$dst/$name"
  done
}

cmd_create() {
  local ref=${1:?usage: create <ref> [--codegen "<cmd>"]} codegen=""
  shift
  [ "${1:-}" = "--codegen" ] && codegen=${2:?--codegen needs a command}
  local root probe
  root=$(git rev-parse --show-toplevel)
  root=$(cd "$root" && pwd -P)
  probe=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
  probe=$(cd "$probe" && pwd -P)
  rmdir "$probe"
  git -C "$root" worktree add --quiet --detach "$probe" "$ref"
  mkdir "$probe/.probe"
  if [ -d "$root/node_modules" ]; then
    mkdir "$probe/node_modules"
    link_entries "$root/node_modules" "$probe/node_modules" "$root" "$probe"
  fi
  # Per-package node_modules folders can hold workspace links too (pnpm puts them
  # there), so they get the same treatment as the root one.
  local nested rel
  while IFS= read -r nested; do
    rel=${nested#"$root"/}
    [ -d "$probe/$(dirname "$rel")" ] && [ ! -e "$probe/$rel" ] || continue
    mkdir "$probe/$rel"
    link_entries "$nested" "$probe/$rel" "$root" "$probe"
  done < <(find "$root" -mindepth 3 -maxdepth 3 -name node_modules -type d -not -path "$root/node_modules/*")
  if [ -n "$codegen" ]; then
    (cd "$probe" && eval "$codegen") >&2 || die "codegen failed: $codegen"
  fi
  echo "$probe"
}

cmd_tsc() {
  local probe=${1:?usage: tsc <dir> <package-dir> <label>} pkg=${2:?package dir} label=${3:?label}
  local tsc=$probe/node_modules/.bin/tsc status=0 out=$probe/.probe/$label.txt
  [ -x "$tsc" ] || die "no tsc at $tsc"
  (cd "$probe/$pkg" && "$tsc" --noEmit -p tsconfig.json --pretty false) > "$out.raw" 2>&1 || status=$?
  grep -E ': error TS[0-9]+' "$out.raw" > "$out" || true
  echo "tsc exit $status · $(wc -l < "$out" | tr -d ' ') errors · saved to $out"
  cat "$out"
}

cmd_diff() {
  local probe=${1:?usage: diff <dir> <label-a> <label-b>} a=${2:?label-a} b=${3:?label-b}
  diff -u "$probe/.probe/$a.txt" "$probe/.probe/$b.txt" && echo "no difference"
}

cmd_remove() {
  local probe=${1:?usage: remove <dir>}
  git worktree remove --force "$probe"
  git worktree prune
  echo "removed $probe"
}

case ${1:-} in
  create | tsc | diff | remove) sub=$1; shift; "cmd_$sub" "$@" ;;
  *) grep -v '^# Copy of ' "$0" | sed -n '2,11p' | sed 's/^# \{0,1\}//'; exit 1 ;;
esac

#!/usr/bin/env bash
# Builds one replay's folder: the case's CONTEXT.md, which holds the request and what the
# past session had verified when it picked a fix. Nothing else, so the player can't read
# later commits that hold the answer.
# Usage: ./setup.sh <dir under /tmp> <case>
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "${1:?usage: setup.sh <dir> <case>}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
name=${2:?usage: setup.sh <dir> <case>}
[ -f "$here/cases/$name/CONTEXT.md" ] || { echo "no case $name" >&2; exit 1; }
rm -rf "$out" && mkdir -p "$out" && cp "$here/cases/$name/CONTEXT.md" "$out/"

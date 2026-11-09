#!/usr/bin/env bash
# Runs focused Franklin e2e specs against the franklin_verify database, from any shell.
# Usage: scripts/e2e.sh <spec path or path:line>... [-- <extra playwright args>]
# Paths are regex-escaped, since Playwright reads filters as regular expressions and
# the "(isolated)" route group would otherwise match nothing.
set -euo pipefail
source "$(dirname "$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$0")")/common.sh"
[ $# -gt 0 ] || { echo "usage: scripts/e2e.sh <spec path or path:line>... [-- <playwright args>]" >&2; exit 2; }

# Playwright's webServer reuses whatever answers on :3000, which would test the wrong
# server and database.
if pid=$(listener "$WEB_PORT") && [ -n "$pid" ]; then
  echo "port $WEB_PORT is in use by pid $pid: run cleanup.sh if a verify run started it, otherwise ask the user" >&2
  exit 1
fi

filters=(); extra=()
while [ $# -gt 0 ]; do
  if [ "$1" = "--" ]; then shift; extra=("$@"); break; fi
  path=${1#apps/web/}
  file=${path%:[0-9]*}; line=${path#"$file"}
  filters+=("$(python3 -c 'import re,sys;print(re.escape(sys.argv[1]))' "$file")$line")
  shift
done

export FRANKLIN_TEST_DATABASE_URL="$(verify_db_url)"
cd "$REPO/apps/web"
echo "e2e in $REPO ($(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)) against franklin_verify"
exec bun run test:e2e -- "${filters[@]}" --reporter=line ${extra[@]+"${extra[@]}"}

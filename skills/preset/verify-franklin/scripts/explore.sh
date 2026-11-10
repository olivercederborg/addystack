#!/usr/bin/env bash
# Signs agent-browser's verify-franklin session in as the seeded owner and opens a page,
# for exploring a feature before writing its recipe. The session cookie stays in the
# run folder. Usage: scripts/explore.sh [path]   (defaults to /)
set -euo pipefail
source "$(dirname "$0")/common.sh"
command -v agent-browser > /dev/null || { echo "agent-browser is missing: npm i -g agent-browser && agent-browser install" >&2; exit 1; }
require_own_web
scripts="$(cd "$(dirname "$0")" && pwd)"
"$scripts/run.sh" "$scripts/sign-in-state.ts" > /dev/null
agent-browser --session verify-franklin state load "$(readlink "$CURRENT")/agent-browser-state.json" > /dev/null
agent-browser --session verify-franklin open "http://localhost:$WEB_PORT${1:-/}" > /dev/null
echo "signed in: agent-browser --session verify-franklin, at $(agent-browser --session verify-franklin get url)"

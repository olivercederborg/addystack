#!/usr/bin/env bash
# Stops the processes this run started. Evidence stays in the run folder.
set -euo pipefail
source "$(dirname "$0")/common.sh"
[ -d "$CURRENT" ] || { echo "no run to clean up"; exit 0; }
for name in web postmark; do
  [ -f "$CURRENT/$name.pid" ] && kill_tree "$(cat "$CURRENT/$name.pid")"
done
# explore.sh's browser and its saved session, which would outlive the run otherwise.
if command -v agent-browser > /dev/null; then agent-browser --session verify-franklin close > /dev/null 2>&1 || true; fi
rm -f "$CURRENT/agent-browser-state.json"
sleep 2
for port in "$WEB_PORT" "$POSTMARK_PORT"; do
  [ -z "$(listener "$port")" ] || echo "⚠️ :$port still has a listener (pid $(listener "$port")); not ours to kill" >&2
done
echo "stopped; evidence kept in $(readlink "$CURRENT")/evidence"

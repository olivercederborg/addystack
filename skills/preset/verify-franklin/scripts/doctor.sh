#!/usr/bin/env bash
# Read-only: is the current run's instance up, ours, and serving this checkout?
set -euo pipefail
source "$(dirname "$0")/common.sh"
[ -d "$CURRENT" ] || { echo "no run; start one with launch.sh" >&2; exit 1; }
status=0
for name in web postmark; do
  port=$([ "$name" = web ] && echo "$WEB_PORT" || echo "$POSTMARK_PORT")
  root=$(cat "$CURRENT/$name.pid")
  pid=$(listener "$port" || true)
  if [ -z "$pid" ]; then echo "❌ $name: nothing listens on :$port"; status=1
  elif descends_from "$root" "$pid"; then echo "✅ $name: :$port served by this run (pid $pid)"
  else echo "❌ $name: :$port belongs to pid $pid, not this run"; status=1; fi
done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_PORT/up" || true)
[ "$code" = 200 ] && echo "✅ /up 200" || { echo "❌ /up $code"; status=1; }
head=$(git -C "$REPO" rev-parse --short HEAD)
[ "$head" = "$(cat "$CURRENT/revision")" ] && echo "✅ checkout at $head, as launched" \
  || { echo "⚠️ checkout moved: launched at $(cat "$CURRENT/revision"), now $head (restart to verify the new code)"; }
exit $status

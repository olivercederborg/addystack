# Shared by the verify-franklin scripts. A run keeps its pids, logs, and evidence in
# /tmp/verify-franklin/<run-id>, and /tmp/verify-franklin/current points at the latest.
# The checkout to verify: VERIFY_REPO, else the Franklin checkout you're in (such as a
# worktree), else the main checkout. The skill lives in the addystack repo, outside any checkout.
MAIN_CHECKOUT="$HOME/Developer/work/franklin/franklin-next"
franklin_checkout() { local top; top=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null) && [ -f "$top/apps/web/playwright.config.ts" ] && echo "$top"; }
REPO="${VERIFY_REPO:-$(franklin_checkout "$PWD" || franklin_checkout "$MAIN_CHECKOUT")}"
[ -n "$REPO" ] || { echo "not in a Franklin checkout; set VERIFY_REPO" >&2; exit 1; }
RUNS=/tmp/verify-franklin
CURRENT="$RUNS/current"
WEB_PORT=3000
POSTMARK_PORT=4010

# Linux lsof skips next dev's server, whose process name is "next-server (v…", so use ss
# there. ss hides other users' pids: print "unknown" so a taken port still counts.
listener() {
  if [ "$(uname -s)" = Linux ]; then
    local line pid
    line=$(ss -Hltnp "sport = :$1" 2>/dev/null | head -1)
    [ -n "$line" ] || return 0
    pid=$(grep -o 'pid=[0-9]*' <<<"$line" | head -1 | cut -d= -f2)
    echo "${pid:-unknown}"
  else
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1
  fi
}

# True when pid $2 is $1 or one of its descendants.
descends_from() {
  local root=$1 pid=$2
  while [ -n "$pid" ] && [ "$pid" != 1 ]; do
    [ "$pid" = "$root" ] && return 0
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  done
  return 1
}

kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

# The verification database: the test env's Postgres server with its own database, so
# runs don't collide with other worktrees' tests or migrations. Never printed.
verify_db_url() {
  (cd "$REPO/packages/prisma" && infisical run --silent --env=test --path=/shared/database -- \
    python3 -c 'import os, urllib.parse as u; p = u.urlsplit(os.environ["POSTGRES_DIRECT_URL"]); print(u.urlunsplit(p._replace(path="/franklin_verify")))') 2>/dev/null
}

# Exits unless the current run serves the web port, so a recipe never drives a server
# another session started, nor its database.
require_own_web() {
  [ -d "$CURRENT" ] || { echo "no run; start one with launch.sh" >&2; exit 1; }
  local pid
  pid=$(listener "$WEB_PORT" || true)
  [ -n "$pid" ] && descends_from "$(cat "$CURRENT/web.pid")" "$pid" \
    || { echo ":$WEB_PORT is not served by this run${pid:+ (pid $pid has it)}; start one with launch.sh" >&2; exit 1; }
}

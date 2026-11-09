#!/usr/bin/env bash
# Starts Franklin web in the test env (its own franklin_verify database, fake Postmark,
# OTP bypass for the seeded dev+local user) and waits until it serves /up. Refuses if
# a port is taken.
set -euo pipefail
source "$(dirname "$0")/common.sh"

for port in "$WEB_PORT" "$POSTMARK_PORT"; do
  if pid=$(listener "$port") && [ -n "$pid" ]; then
    echo "port $port is in use by pid $pid ($(ps -o comm= -p "$pid")): run cleanup.sh if a verify run started it, otherwise ask the user before stopping it" >&2
    exit 1
  fi
done

run="$RUNS/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$run/evidence"
ln -sfn "$run" "$CURRENT"
git -C "$REPO" rev-parse --abbrev-ref HEAD > "$run/branch"
git -C "$REPO" rev-parse --short HEAD > "$run/revision"

# franklin_verify gets this checkout's migrations (deploy never drops data), then the
# seed upserts the dev+local user and its companies. A failed deploy means the database
# drifted, for example after a branch with conflicting migrations: ask the user before
# resetting it, since a reset deletes all its data.
export FRANKLIN_TEST_DATABASE_URL="$(verify_db_url)"
echo "migrating and seeding franklin_verify (logs in $run)"
(cd "$REPO" && bun run db:test:migrate) > "$run/migrate.log" 2>&1 \
  || { echo "migrate deploy failed (drift?); see $run/migrate.log and ask the user before any reset" >&2; exit 1; }
(cd "$REPO" && bun run db:test:seed) > "$run/seed.log" 2>&1 || { echo "seed failed; see $run/seed.log" >&2; exit 1; }

cd "$REPO/apps/web"
nohup bun test/support/fake-postmark/server.ts > "$run/postmark.log" 2>&1 &
echo $! > "$run/postmark.pid"
# apps/web's test:next, except TEST_OTP_CREDENTIALS is set after infisical: the test
# env defines its own value for another account, which would replace ours.
POSTMARK_API_URL="http://127.0.0.1:$POSTMARK_PORT" nohup infisical run --silent --env=test --path=/web -- \
  ../../scripts/with-test-database.sh env TEST_OTP_CREDENTIALS="dev+local@hifranklin.com:123456" \
  "$REPO/node_modules/.bin/next" dev --port "$WEB_PORT" --turbopack > "$run/web.log" 2>&1 &
echo $! > "$run/web.pid"

for _ in $(seq 1 180); do
  if curl -fs -o /dev/null "http://127.0.0.1:$WEB_PORT/up"; then
    echo "ready: http://localhost:$WEB_PORT ($(cat "$run/branch") @ $(cat "$run/revision")), run $run"
    exit 0
  fi
  sleep 1
done
echo "web did not answer /up within 180s; see $run/web.log" >&2
exit 1

#!/usr/bin/env bash
# Runs a recipe script with the test env's secrets (no secret is printed) against the
# running instance, then rebuilds the run's gallery page. Usage: scripts/run.sh features/<feature>.ts
set -euo pipefail
source "$(dirname "$0")/common.sh"
recipe="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
require_own_web
scripts="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO/apps/web"
status=0
FRANKLIN_TEST_DATABASE_URL="$(verify_db_url)" VERIFY_RUN="$(readlink "$CURRENT")" infisical run --silent --env=test --path=/web -- \
  ../../scripts/with-test-database.sh bun "$recipe" || status=$?
echo "gallery: $("$scripts/gallery.sh")"
exit "$status"

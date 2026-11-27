#!/usr/bin/env bash
# Runs one read-only SQL query on last night's production replica. Usage: scripts/replica.sh "<sql>"
set -euo pipefail
exec sqlite3 -readonly -header "$(cd "$(dirname "$0")/.." && pwd)/.replica/prod.db" "$1"

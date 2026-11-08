#!/usr/bin/env bash
# Fails when a SKILL.md grows past 14,100 bytes: the largest skill after the Oct 2026
# cuts (autopilot, 13,436 bytes) plus 5%, so a skill grows only by replacing words.
# After auto-compaction, Claude Code re-attaches only the first 5,000 tokens of each
# invoked skill (about 17,500 bytes), so a longer skill would lose its last steps.
# Move branch-only material to references/ to get back under it.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
limit=14100
status=0
for skill in "$root"/skills/*/*/SKILL.md; do
  size=$(wc -c < "$skill" | tr -d ' ')
  if [ "$size" -gt "$limit" ]; then
    echo "${skill#$root/} is $size bytes, over $limit: move branch-only material to references/" >&2
    status=1
  fi
done
exit $status

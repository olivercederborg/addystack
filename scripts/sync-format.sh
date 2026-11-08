#!/usr/bin/env bash
# Copies shared/format-pointer.md into every SKILL.md between the toolkit-format markers.
# The references/format.md and views.md the pointer sends agents to are copies that
# scripts/copies.txt lists and scripts/sync-copies.py writes; its --check fails when a
# skill with the pointer lacks them.
# Usage: scripts/sync-format.sh          # write
#        scripts/sync-format.sh --check  # exit 1 if any pointer differs
set -euo pipefail
[[ -z "${1:-}" || "$1" == "--check" ]] || { echo "usage: $0 [--check]" >&2; exit 2; }
root="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$root" "${1:-}" <<'PY'
import pathlib, re, sys
root, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
block = (root / "shared/format-pointer.md").read_text().strip()
pattern = re.compile(r"<!-- toolkit-format:start.*?<!-- toolkit-format:end -->", re.S)
stale, without = [], []
for skill in sorted(root.glob("skills/*/*/SKILL.md")):
    text = skill.read_text()
    if not pattern.search(text):
        without.append(skill.parent.name)
        continue
    synced = pattern.sub(lambda _: block, text)
    if synced != text:
        stale.append(str(skill.relative_to(root)))
        if mode != "--check":
            skill.write_text(synced)
if without:
    print("Skills without a format pointer:", ", ".join(without))
if mode == "--check" and stale:
    print("Out of sync with shared/format-pointer.md:", *stale, sep="\n  ")
    sys.exit(1)
print("synced" if mode != "--check" else "format pointers in sync", *stale, sep="\n  ")
PY

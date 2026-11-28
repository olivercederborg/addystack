#!/usr/bin/env bash
# Builds a catch-up fixture: a log of the work done since the user's last message, and
# the two header screenshots that work captured. Usage: setup.sh <dir>
set -euo pipefail
dir="${1:?usage: setup.sh <dir>}"
# Resolve `..` and symlinks first, so the guard sees where the files land. rm -rf on a
# symlink removes only the link, so delete the caller's path, as the log spells it.
real=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$dir")
case "$real" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $real" >&2; exit 1;; esac
rm -rf "$dir" && mkdir -p "$dir/screenshots"
python3 - "$dir/screenshots" <<'PY'
import struct, sys, zlib
def png(path, rgb):
    w, h = 320, 80
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
png(sys.argv[1] + "/header-compact.png", (30, 60, 120))
png(sys.argv[1] + "/header-tall.png", (120, 60, 30))
PY
cat > "$dir/session-log.md" <<EOF
# Work since the user's last message

The user's last message: "split the settings rework into PRs, and show me the new header."

- Opened six PRs on acme/web, all green, all verified by a fresh verifier, each waiting
  on the user's merge call. The user owns merging.
  - #101 Move settings routes under /settings. Changes every settings URL; old URLs
    redirect. Verifier drove each old URL. Risk: medium, bookmarks rely on redirects.
  - #102 Rename "Workspace" to "Team" in settings copy. Copy only. Risk: low.
  - #103 Store notification prefs per team instead of per user. Migrates existing rows.
    Verifier ran the migration on a copy of staging. Risk: high, a data migration.
  - #104 Add a loading skeleton to the billing page. Verifier captured no screenshot.
    Risk: low.
  - #105 Drop the unused legacy settings API. No callers found in the repo or logs for
    30 days. Risk: medium, an external script could still call it.
  - #106 Fix the avatar upload size check, which accepted 50 MB files. Found and fixed
    on the way. Risk: low.
- Built two header designs for the settings page. The user must pick one; the work
  weighed only these two.
  - Compact: one 48 px row, fits the mobile layout, but hides the team switcher in a
    menu. Screenshot: $dir/screenshots/header-compact.png
  - Tall: two rows, 96 px, keeps the team switcher visible, but pushes content below
    the fold on small laptops. Screenshot: $dir/screenshots/header-tall.png
- A CI run on #103's follow-up branch is still running.
EOF

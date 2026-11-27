#!/usr/bin/env bash
# Builds an addystack scenario in <dir>: a checkout at <dir>/work/app with an origin
# remote, a config at <dir>/config/addystack.jsonc, and `addystack build` run with every
# path inside <dir>, so nothing outside it is read or written. <dir>/env.sh exports the
# overrides, a HOME at <dir>/home so `install` can't touch the runner's host settings,
# and KIT, the addystack tool's folder in the ADDYSTACK_KIT checkout (maintainer/kit_path.py).
# `explain` adds a rule that keeps <dir>/work/* at a draft stack, with defaults that
# merge; `change` has only those defaults.
# Usage: ./setup.sh <target-dir> explain | change
set -euo pipefail
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/as-eval}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
kind="${2:-explain}"
kit="$(python3 "$(dirname "$0")/../../maintainer/kit_path.py" --tool)"
rm -rf "$out" && mkdir -p "$out/config" "$out/work/app" "$out/home"
git -C "$out/work/app" init -q -b main
git -C "$out/work/app" remote add origin git@github.com:acme/app.git
git -C "$out/work/app" -c user.name=Sam -c user.email=sam@example.com commit -q --allow-empty -m "Start"
case "$kind" in
  explain) rule=",
    \"repos\": [
      { \"match\": { \"path\": \"$out/work/*\" }, \"planning\": \"gated\", \"trust\": \"draft\" }
    ]" ;;
  change) rule="" ;;
  *) echo "usage: $0 <target-dir> explain | change" >&2; exit 2 ;;
esac
cat > "$out/config/addystack.jsonc" <<JSONC
// Sam's addystack config.
{
  "version": 1,
  "identity": { "name": "Sam" },
  "hosts": { "claude": false, "codex": false },
  // Personal work: agents may merge when Sam's go names it.
  "policy": {
    "defaults": { "planning": "autonomous", "trust": "merge-on-go" }$rule
  }
}
JSONC
cat > "$out/env.sh" <<ENV
export ADDYSTACK_CONFIG="$out/config/addystack.jsonc" ADDYSTACK_STATE="$out/state"
export ADDYSTACK_CLAUDE_MD="$out/claude/CLAUDE.md" ADDYSTACK_CODEX_MD="$out/codex/AGENTS.md"
export HOME="$out/home" KIT="$kit"
ENV
. "$out/env.sh"
python3 "$kit/bin/addystack" build >/dev/null
test -f "$out/state/resolved.json"

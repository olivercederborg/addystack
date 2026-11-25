#!/usr/bin/env bash
# Given `<from> <to>`, as .githooks/pre-push gives a push's range, exits 0 when those commits
# change a file the hook tests (the addystack skill's hooks/test_*.py) depend on, and 1 when
# they don't, so the push runs them on this machine (the macOS-only ones, or all on a host
# fallback) only then. Those files are everything under that hooks/, the
# kit files a hook or hook test names as `HOOKS.parent / "…"` or `.parent.parent / "…"`,
# and the checkout's files a hook test names as `REPO / "…"`, plus the config files
# resolved.py's fallback and test_resolved.py read through lib/;
# scripts/test_hook_inputs_staged.py fails when a named one is missing.
set -euo pipefail
[ $# = 2 ] || { echo "usage: hook-inputs-staged.sh <from> <to>" >&2; exit 2; }
inputs=(skills/primitive/addystack/hooks skills/optional/reply-shape/SKILL.md replies.md
        skills/primitive/addystack/scripts/stack.sh skills/primitive/addystack/lib
        skills/primitive/addystack/addystack.defaults.jsonc skills/primitive/addystack/schema
        skills/primitive/addystack/bin skills/primitive/addystack/core skills/primitive/addystack/commands
        skills/primitive/review-loop/scripts/verdicts.py)
cd "$(git rev-parse --show-toplevel)"
# --no-renames lists both sides, so a rename out of the hooks folder counts.
! git diff --quiet --no-renames "$1" "$2" -- "${inputs[@]}"

#!/usr/bin/env bash
# Exits 0 when the commit being made changes a file the hook tests (the addystack skill's
# hooks/test_*.py) depend on, and 1 when it doesn't, so the pre-commit hook skips them
# (about 3 minutes) on other commits. Those files are everything under that hooks/, the
# kit files a hook or hook test names as `HOOKS.parent / "…"` or `.parent.parent / "…"`,
# and the checkout's files a hook test names as `REPO / "…"`, plus the config files
# resolved.py's fallback and test_resolved.py read through lib/;
# scripts/test_hook_inputs_staged.py fails when a named one is missing.
# Run it before unsetting git's repo-local variables: a `git commit <paths>` stages into a
# temporary index that only GIT_INDEX_FILE names.
set -euo pipefail
inputs=(skills/primitive/addystack/hooks skills/optional/reply-shape/SKILL.md replies.md
        skills/primitive/addystack/scripts/stack.sh skills/primitive/addystack/lib
        skills/primitive/addystack/addystack.defaults.jsonc skills/primitive/addystack/schema
        skills/primitive/addystack/bin skills/primitive/addystack/core
        skills/primitive/addystack/references/turn-block.md
        skills/primitive/review-loop/scripts/verdicts.py)
cd "$(git rev-parse --show-toplevel)"
# --no-renames lists both sides, so a rename out of the hooks folder counts.
! git diff --cached --quiet --no-renames -- "${inputs[@]}"

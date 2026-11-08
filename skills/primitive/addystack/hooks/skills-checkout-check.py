#!/usr/bin/env python3
"""SessionStart: keep the skills checkout that Claude Code's skill folder links into on
`origin/main`, since merged skill changes don't load until it is. Added after a checkout
sat on a merged branch, 29 commits behind, while sessions loaded its stale skills (Oct
2026). Reads only local refs, so it needs no network and stays fast.

On a clean `main` that's behind, it fast-forwards and says nothing. Otherwise it warns,
and on another branch only once a day per branch: in the month to Oct 29, 2026 it warned
in 179 sessions, one branch for 9 days. Also warns when this machine's installed hooks
drift from manifest.json (hook_parity.py), since a second machine once ran a week-old hook set,
5 hooks short, unnoticed."""
import datetime, json, os, pathlib, shutil, subprocess, sys

import hook_parity

json.load(sys.stdin)
link = (pathlib.Path(os.environ["SKILLS_LINK"]).expanduser() if os.environ.get("SKILLS_LINK")
        else hook_parity.config.claude_home() / "skills" / "reply-shape")


def git(*args):
    result = subprocess.run(["git", "-C", str(link.resolve().parent), *args],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def warned_today(branch):
    """True when this branch was already warned about today; records it otherwise."""
    state = pathlib.Path(git("rev-parse", "--absolute-git-dir"), "skills-checkout-warned")
    today = str(datetime.date.today())
    entry = f"{today} {branch}"
    try:
        seen = state.read_text().splitlines() if state.exists() else []
        if entry in seen:
            return True
        state.write_text("\n".join([line for line in seen if line.startswith(today)] + [entry]) + "\n")
    except OSError:
        pass
    return False


def checkout_warning():
    repo = git("rev-parse", "--show-toplevel") if link.exists() else ""
    if not repo:
        return ""
    branch = git("branch", "--show-current") or "a detached HEAD"
    behind = git("rev-list", "--count", "HEAD..origin/main") or "0"
    if branch == "main" and behind != "0" and not git("status", "--porcelain", "--untracked-files=no"):
        git("merge", "--ff-only", "-q", "origin/main")
        behind = git("rev-list", "--count", "HEAD..origin/main") or "0"
    if branch == "main" and behind == "0":
        return ""
    if branch != "main" and warned_today(branch):
        return ""
    where = f"is on {branch}" if branch != "main" else "is on main"
    lag = f", {behind} commits behind origin/main" if behind != "0" else ""
    return (f"⚠️ The skills checkout at {repo} {where}{lag}, so this session loads "
            "skills that differ from main.")


# The checkout first, since a fast-forward can change the manifest drift reads.
checkout = checkout_warning()
drift = hook_parity.drift("claude") + hook_parity.drift("codex", required=bool(shutil.which("codex")))
warnings = [checkout] + ([
    "⚠️ This machine's hooks differ from hooks/manifest.json, so some checks don't run as "
    f"declared (recheck with `python3 {hook_parity.__file__} --codex-trust`): " + "; ".join(drift) + "."]
    if drift else [])
warnings = [warning for warning in warnings if warning]
if warnings:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": " ".join(warnings) + " Tell the user in your first reply, "
                             "before relying on a skill's rules.",
    }}))

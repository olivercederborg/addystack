#!/usr/bin/env python3
"""PermissionRequest on Bash: in bypass permissions mode, deny an ask for a command that
names no removal, with a hint to rewrite it, so the agent goes on instead of waiting on
the user. Claude Code 2.1.309 started asking "Dangerous rm operation not ruled out: the
shell may read this command differently than it was parsed" whenever its bash parser
can't read a command, and zsh-only syntax such as `${(f)...}` is enough. 2.1.308 ran the
same command without asking. In the week to Oct 29, 2026, T3 showed the user 103 such asks
and they approved 102.

Bypass mode only asks for the checks it can't skip, so a deny here never lets a command
run: the agent rewrites it into a form Claude Code can check. A command that names a
removal (`rm`, `find -delete`, `git clean`, `git worktree remove`, `git branch -D`, or any
`delete` or `remove`) gets no decision, so its ask still reaches the user."""
import json, re, sys

REMOVAL = re.compile(r"\b(?:rm|rmdir|unlink|shred|srm|trash|delete|remove)\b|\bgit\b[^;&|\n]*\sclean\b"
                     r"|\bgit\b[^;&|\n]*\sbranch\b[^;&|\n]*\s-[a-zA-Z]*[dD]\b")

try:
    payload = json.load(sys.stdin)
    command = payload["tool_input"]["command"]
    unsandboxed = payload["tool_input"].get("dangerouslyDisableSandbox") is True
    mode = payload.get("permission_mode")
except (ValueError, KeyError, TypeError):
    sys.exit(0)

# A retry outside the sandbox asks for the user's okay even in bypass mode, and parses fine.
if mode != "bypassPermissions" or unsandboxed or not isinstance(command, str) or REMOVAL.search(command):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
        "behavior": "deny",
        "message": "Claude Code couldn't check this command for dangerous removals, which usually means "
                   "its bash parser can't read it: zsh-only syntax (`${(f)...}`, `${${...}}`, "
                   "`typeset -A`), `eval` of a built string, or tangled quoting. Rewrite it in plain bash "
                   "syntax, such as a `while IFS= read -r` loop, with no zsh-only expansions. Or write the "
                   "script to a file and run it with `bash script.sh` or `python3 script.py`. Don't retry "
                   "it unchanged.",
    },
}}))

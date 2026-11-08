#!/usr/bin/env python3
"""PreToolUse on Bash: in a repo whose policy pushes through gh stack
(`resolved.policy(d).pushVia == "gh-stack"`: a rule in the user's addystack config, the
repo's own .agents/addystack.jsonc, or policy.unresolved when its origin can't be read),
deny `gt`, `git push`, and `gh pr create`, and point at the gh stack command that replaces
each.
A work repo moved from Graphite to gh stack in October 2026, but its repo docs and
`.graphite_repo_config` still point agents at `gt`. Other repos are untouched.
Added as graphite-only.py after 28 plain-git pushes and branches in 5 of its sessions,
counted with `transcript.py scan --hook` (to Oct 3, 2026).

Creating a branch with git stays allowed: `gh stack init` and `gh stack add` adopt an
existing branch. A screenshot for a PR goes up with `gh pr edit --attach`, which the push
advice names, since agents had pushed screenshots to a gist clone. An exception for a gist
clone's push, judged from the shell text, kept letting its pushes through (Oct 23,
2026). Known limits, since regexes can't parse shell: git global options other than
`-C`, `gt` run by its path, a command that runs only inside quotes or a heredoc body, and
a bare `gt` argument (`echo gt`), which is denied too."""
import json, os, re, sys

import resolved

payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")
cwd = payload.get("cwd") or os.getcwd()

# Heredoc bodies and quoted strings are data (PR bodies, grep patterns), not commands.
# Whatever is left is matched wherever it appears, so loops, conditionals, prefixes, and
# wrappers (`if gt sync`, `CI=1 gt submit`, `timeout 60 git push`) need no list of their own.
code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)
code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
# `gt` is a whole word: `-gt` in a test, `$gt`, and a path ending in `/gt` stay allowed.
forbidden = re.compile(r"(?<![-\w./$])(gt)(?![-\w.])"
                       r"|\b(git(?:\s+-C\s+\S+)?\s+push|gh\s+pr\s+create)\b")
match = forbidden.search(code)
if not match:
    sys.exit(0)

def expand(path):
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(path.strip("'\""))))

# A cd path ends where the shell's next word or operator starts.
dirs = [cwd] + [expand(p) for p in re.findall(r"\bcd\s+([^\s;&|)]+)", command)] \
             + [expand(p) for p in re.findall(r"\bgit\s+-C\s+(\S+)", command)]

if not any(os.path.isdir(d) and resolved.policy(d).pushVia == "gh-stack" for d in dirs):
    sys.exit(0)

instead = {
    "gt": "`gh stack add` for `gt create`, `git commit` for `gt modify`, `gh stack submit --auto` for `gt submit`, "
          "`gh stack rebase` for `gt restack`, and `gh stack sync` for `gt sync` (see the `gh-stack` skill; "
          "`gh stack modify` is an interactive screen an agent can't drive). The repo's Graphite docs are out of date",
    "push": "`gh stack push`, or `gh stack submit --auto` to also open draft PRs. To put screenshots in a PR, run "
            "`gh pr edit <n> --attach '<file>#<alt text>'`, which uploads them into its description",
    "create": "`gh stack submit --auto`, which opens draft PRs; mark one ready with `gh pr ready N`",
}
used = match.group(1) or match.group(2)
words = used.split()
key = "gt" if words[0] == "gt" else words[-1]
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": f"This repo pushes through gh stack, so `{used}` is blocked: use {instead[key]}. "
                                "Start a stack with `gh stack init <name>` and add a layer with `gh stack add <name>`; "
                                "both adopt a branch that already exists.",
}}))

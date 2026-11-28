#!/usr/bin/env python3
"""PreToolUse on Bash: in a checkout whose policy has pushVia `gh-stack`, denies `gh pr create`
(or `gh pr new`) with a `--base` other than the repo's default branch. Such a PR shows its
base's diff, but GitHub has no stack for it, so the stack's UI and `gh stack merge`
miss it. The denial names the gh stack way to open it.
From Nov 14 to 28, 2026, agents in 12 sessions stacked a PR with `gh pr create --base <branch>`,
7 of them after running `gh stack init` or `add` earlier, typically for a layer built in
another worktree than the stack's, on a work repo and on this kit's own repo.
`gh stack link` builds or grows the GitHub stack from branch names or PR numbers, with no
local stack, so it covers that case.
It reads the command as push-gate.py does, without the heredoc bodies, quoted strings,
redirections, and comments, and each create's checkout through shell_dirs.Walk. It passes
when it can't tell: a base or repo only the shell can expand, a checkout it can't place, or a
default branch `gh repo view` can't read. `--dry-run '<command>'` prints the verdict."""
import json, os, re, subprocess, sys

DRY_RUN = sys.argv[1:2] == ["--dry-run"]
payload = {"tool_input": {"command": " ".join(sys.argv[2:])}} if DRY_RUN else json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")


def passes(why):
    if DRY_RUN:
        print(f"would pass: {why}")
    sys.exit(0)


if not re.search(r"\bgh\b.*\bpr\s+(?:create|new)\b", command, re.S):  # most commands: no parse, no gh
    passes("no `gh pr create`")

from shell_dirs import ASSIGNMENT, HEREDOC, QUOTED, Walk, flag, unreadable

code = HEREDOC.sub("", command)
code = re.sub(r"'((?!#)[^'\s;&|<>]*)'|\"((?!#)[^\"\s;&|<>\\$`]*)\"", lambda m: m.group(1) or m.group(2) or "''", code)
code = QUOTED.sub("''", code)
code = re.sub(r"\d*(?:>>?|<)(?:&\d+-?|\s*[^\s;&|]+)", " ", code)
code = re.sub(r"(?:(?<=[;&|(`])|(?<=(?<!\\)\s)|^)#[^\n]*", "", code, flags=re.M)

walk = Walk(code, payload.get("cwd") or os.getcwd())
creates = []  # (base, -R repo or None, checkout)
for _, words, lead in walk:
    words = [word for word in words[lead:] if not ASSIGNMENT.match(word)]
    if "gh" not in words:
        continue
    args = words[words.index("gh") + 1:]
    named = [word for word in args if not word.startswith("-")]
    if named[:2] not in (["pr", "create"], ["pr", "new"]) or {"-h", "--help"} & set(args):
        continue
    base, repo = flag(args, "-B", "--base"), flag(args, "-R", "--repo")
    if base and not unreadable(base) and not (repo and unreadable(repo)) and "dir" not in walk.unknown:
        creates.append((base, repo, walk.cwd))
if not creates:
    passes("no `gh pr create` with a `--base` the gate can read")

import resolved  # here, so a broken config module fails only a create with a base

for base, repo, where in creates:
    try:
        if resolved.policy(where).pushVia != "gh-stack":
            continue
        view = subprocess.run(["gh", "repo", "view", *([repo] if repo else []), "--json", "defaultBranchRef",
                               "-q", ".defaultBranchRef.name"], cwd=where, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):  # a checkout that isn't there yet, or a slow gh
        continue
    trunk = view.stdout.strip()
    if view.returncode or not trunk or base == trunk:
        continue
    reason = (f"Stack gate: `gh pr create --base {base}` opens a PR GitHub doesn't show in a stack. Open it with gh "
              f"stack instead. In the checkout that holds the stack: `gh stack add <branch>`, commit, then "
              f"`gh stack submit --auto`. For a branch built elsewhere, such as another worktree: push it, then "
              f"`gh stack link {base} <branch>`, which opens a draft PR on {base} and puts both in one stack; "
              f"`gh pr edit` then sets its title and body. A PR that belongs on {trunk} takes `--base {trunk}`.")
    if DRY_RUN:
        print(reason + "\nwould deny")
        sys.exit(1)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    sys.exit(0)
passes("every base is its repo's default branch, or the repo doesn't stack with gh stack")

#!/usr/bin/env python3
"""PreToolUse on Bash, and on Write, Edit, and MultiEdit in Claude Code: in a coordinator
thread, a T3 thread whose title holds `◆ <project>`, denies what builds, tests, or changes
a repo or PR, and points at the PR's worker or a subthread. The user talks to the
coordinator, so it stays free: it routes, answers, writes project.md, and reads diffs, PR
state, and threads. `gh pr ready` and the merge line still run here after the user's go,
since merge-gate trusts a go only from their own prompt in the transcript that merges.
Added after the ◆ tower-app coordinator ran `swift build` and `swift test` 35 times
inline, and the user couldn't talk to it meanwhile. Replayed on the 1,664 commands of the
past ◆ threads in T3's state database (counted 2026-10-31), it denies 132, in 4 of 9
threads; a sample read found no false positive.

It nudges a habit; it isn't a security boundary, so any doubt allows: outside T3, no
session id, or a state database that can't be read or holds no ◆ title. Known limits: a
command inside quotes or `bash -c`, or behind more than 4 wrappers, isn't seen; a Bash
write such as a redirect isn't checked, since project.md is written that way too; Codex
runs only the Bash check, since it runs PreToolUse hooks only for Bash; and a thread
before it takes its ◆ title isn't a coordinator yet."""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_child  # noqa: E402

# Only a command position counts: the start of a line or pipeline segment, a
# substitution, a condition, or a loop or branch body, after up to 4 wrappers and an
# optional path.
START = (r"(?:^|[;&|(`{\n]|\$\()\s*(?:(?:then|do|else|elif|if|while|until|!)\s+)*"
         r"(?:(?:\w+=\S*|command|exec|nohup|time|env|caffeinate)\s+){0,4}(?:\S*/)?")
HEAVY = [
    r"swift\s+(?:build|test|run)\b", r"xcodebuild\b", r"xcrun\b",
    r"npm\s+(?:test|run|install|i|ci|add|exec|x)\b", r"npx\b", r"bunx\b",
    # pnpm, yarn, and bun run a package script or a file by its bare name, as in `pnpm build`.
    r"(?:pnpm|yarn|bun)\s+(?!(?:why|list|ls|info|view|outdated|-v|--version)(?=[\s;&|)`]|$))[\w./:-]+",
    r"(?:tsc|vitest|jest|playwright|pytest|cargo|gradlew?|make)\b", r"go\s+(?:build|test|run|vet)\b",
    r"python3?\s+(?:-\w+\s+)*(?:-m\s+(?:pytest|unittest)\b|\S*test_\w*\.py\b)",
    r"git\s+(?:-[Cc]\s+\S+\s+)*(?:commit|push|rebase|cherry-pick|merge|am|revert|reset|apply)(?=\s|$)",
    r"gh\s+stack\s+(?:push|submit|rebase|sync|add|init|unstack|checkout|modify|amend)\b",
    r"gh\s+pr\s+(?:edit|create|comment|review|close|reopen|checkout)\b",
    r"stack\.sh\s+(?:restack|start)\b",
]
END = r"(?=[\s;&|)`]|$)"
PATTERN = re.compile(START + "((?:" + "|".join(h.removesuffix(r"\b") for h in HEAVY) + ")" + END + ")[^;&|\n]*", re.M)


def code_of(command):
    """The command without heredoc bodies and quoted strings, which are data. A heredoc's
    opener line stays, since it is code."""
    code = command.replace("\\\n", " ")
    code = re.sub(r"([^\n]*<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2\b", r"\1", code, flags=re.S)
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)


def heavy(command):
    """The heavy command word the command runs, such as `swift test`, or None. A call
    asking for `--help` or `-h` only reads."""
    for match in PATTERN.finditer(code_of(command)):
        # A help flag after `--` goes to the script, as in `npm run build -- --help`.
        if not re.search(r"\s(?:--help|-h)(?=\s|$)", re.split(r"\s--(?=\s|$)", match.group(0))[0]):
            return re.sub(r"\s+", " ", match.group(1))
    return None


def in_work_tree(path):
    """True when path, or a folder above it, holds `.git`, a file or a folder."""
    path = Path(os.path.realpath(os.path.expanduser(path)))
    return any((folder / ".git").exists() for folder in [path, *path.parents])


if not os.environ.get("T3CODE_CLI_PATH"):
    sys.exit(0)
try:
    payload = json.load(sys.stdin)
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input") or {}
    if tool == "Bash":
        command = tool_input.get("command")
        found = heavy(command) if isinstance(command, str) else None
        what = f"`{found}` builds, tests, or changes a repo or PR"
    elif tool in ("Write", "Edit", "MultiEdit"):
        target = tool_input.get("file_path")
        found = target if isinstance(target, str) and target and in_work_tree(target) else None
        what = f"`{found}` is in a repo, so editing it changes the repo"
    else:
        found = None
    if not found or not t3_child.coordinator_project(payload.get("session_id")):
        sys.exit(0)
except (ValueError, AttributeError, OSError):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "This ◆ coordinator thread stays free for the user: it routes, answers, writes "
                                f"project.md, and reads diffs, PR state, and threads. {what}: send it to the "
                                "PR's worker or a subthread (coordinator step 3). After the user's go, "
                                "`gh pr ready` and the merge line run here (step 6).",
}}))

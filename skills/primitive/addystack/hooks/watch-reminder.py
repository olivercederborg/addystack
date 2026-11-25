#!/usr/bin/env python3
"""PostToolUse on T3's `pull_request_update` and `pull_request_create`, and on Bash: after
a call that leaves a PR waiting on reviewers, tells the agent to watch it before ending
the turn, with `until: "checks"`, so the thread returns to the user's inbox once checks
finish and the watch still wakes it on reviews and comments. The calls are
`pull_request_update` with `ready: true`, `state: "open"`, or `requestReviewers`,
`pull_request_create` without `draft: true`, and a Bash command that runs `gh pr ready`
(not `--undo`), `gh pr reopen`, `gh pr edit --add-reviewer`, `gh pr create` without
`--draft`, or `gh stack submit --open`. A reopen counts since T3 ends a watch when its PR
closes. The call can't tell a draft, another author's PR, or a stack's several PRs, so the
reminder asks for a watch on each open, ready PR of the user's it left. On Nov 25, 2026 an agent requested two reviews on a work repo's #6215 and ended the turn
with no watch, and the user had to say "watch it"; the reply rules asked for a watch only
after a push or a new PR. unwatch-gate.py keeps such a watch on afterwards.

It reads the command as text, so a `gh pr ready` inside quotes or a heredoc reminds too,
which costs a line of context. A T3 delegated child gets no reminder: the thread it
reports to owns the watch. It never blocks: on any input it doesn't expect, it adds
nothing."""
import json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

BASH = re.compile(r"\bgh\s+pr\s+(?:ready\b(?![^\n;&|]*--undo)|reopen\b)"
                  r"|\bgh\s+pr\s+edit\b[^\n;&|]*--add-reviewer\b"
                  r"|\bgh\s+pr\s+create\b(?![^\n;&|]*(?:--draft\b(?!=false)|\s-d\b))"
                  r"|\bgh\s+stack\s+submit\b[^\n;&|]*--open\b")
# The call alone can't tell a draft, another author's PR, or a PR that already existed, and
# `gh stack submit --open` readies a whole stack, so the agent checks which PRs it left waiting.
REMINDER = ("This call may have left PRs waiting on reviewers. Before ending the turn, call "
            '`watch_pull_request` with `until: "checks"` on each one that is open, ready (not a draft), '
            "and the user's, unless this thread already watches it: the thread returns to the user's inbox "
            "once checks finish, and the watch still wakes it on reviews, comments, and failed checks. Keep "
            "the watch on while the PR is open and ready.")


def waits_on_reviewers(tool, tool_input):
    if tool == "mcp__t3-code__pull_request_update":
        return (tool_input.get("ready") is True or tool_input.get("state") == "open"
                or bool(tool_input.get("requestReviewers")))
    if tool == "mcp__t3-code__pull_request_create":
        return tool_input.get("draft") is not True
    if tool == "Bash":
        return isinstance(tool_input.get("command"), str) and bool(BASH.search(tool_input["command"]))
    return False


try:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or not waits_on_reviewers(payload.get("tool_name"), tool_input):
        sys.exit(0)
    import t3_child
    if t3_child.delegated_brief(payload.get("session_id")) is not None:
        sys.exit(0)
except (ValueError, AttributeError):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": REMINDER}}))

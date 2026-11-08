#!/usr/bin/env python3
"""Stop: in a T3 thread, send the agent back when its turn pushed or opened a PR and left
no T3 watch on it, so a failing check or a review wakes the thread instead of the user.

In the week to Oct 22, 2026, 40 of 44 threads that opened or readied a PR never called
watch_pull_request, and the user was the one to say "CI is failing" in three of them. The
check counts a successful `gh stack submit|push|sync` or `gh pr create|ready` this turn. It
passes when a watch on any PR is running from earlier in the session and no PR was opened
since (`gh pr create`, a submit that printed "Created PR", or `gh pr ready` on a PR no watch
names, which starts a draft's CI and review bots for the first time), when the turn later
merged or unwatched (babysit's hand-back at maintenance done), when the session isn't in
T3, for T3 delegated children, whose parent owns the PR, and when neither the session's
folder nor any folder the turn `cd`s into is a repo with workflows in .github/workflows,
since a watch there has no checks to wake on. Claude Code transcripts only: Codex logs its
tool calls in shapes this doesn't read yet."""
import json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, transcripts  # noqa: E402

PUSH = re.compile(r"\bgh\s+(?:stack\s+(submit|push|sync)|pr\s+(create|ready))\b(?![^;&|\n]*(?:--help|-h\b|--undo))")
MERGE = re.compile(r"\bgh\s+(?:pr|stack)\s+merge\b")
PR_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
# The PR a `gh pr ready` names, by number or URL, among the rest of its command.
READY_PR = re.compile(r"[^;&|\n]*?(?<!\S)(?:\S*/pull/)?(\d+)(?!\S)")


def pr_key(tool_input):
    """The PR a watch call names, as "owner/repo#N", from its url or its repository and number."""
    if match := PR_URL.search(str(tool_input.get("url") or "")):
        return f"{match.group(1)}#{match.group(2)}"
    return f"{tool_input.get('repository') or ''}#{tool_input.get('number') or ''}"


def text(value):
    """A transcript value that should be a string, or "" when it isn't one."""
    return value if isinstance(value, str) else ""


def tool_calls(path):
    """Each tool call in the transcript, oldest first, as (turn, name, detail, failed, output):
    the detail is a Bash call's command, or the PR a watch call names."""
    calls, failed, outputs, turn = [], set(), {}, 0
    with open(path) as transcript:
        for line in transcript:
            try:
                entry = json.loads(line)
            except (ValueError, RecursionError):  # Python 3.9 recurses on deep nesting
                continue
            if transcripts.entry_text(entry):
                turn += 1
            message = entry.get("message") if isinstance(entry, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    name, tool_input = text(part.get("name")), part.get("input")
                    tool_input = tool_input if isinstance(tool_input, dict) else {}
                    detail = pr_key(tool_input) if name.endswith("watch_pull_request") \
                        else text(tool_input.get("command"))
                    calls.append((turn, name, detail, text(part.get("id"))))
                elif part.get("type") == "tool_result":
                    if part.get("is_error"):
                        failed.add(text(part.get("tool_use_id")))
                    outputs[text(part.get("tool_use_id"))] = json.dumps(part.get("content"))
    return [(turn, name, detail, ref in failed, outputs.get(ref, ""))
            for turn, name, detail, ref in calls], turn


def has_ci(folder):
    """True when folder sits in a git repo whose .github/workflows holds a workflow file."""
    try:
        root = subprocess.run(["git", "-C", folder, "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
        workflows = Path(root) / ".github" / "workflows"
        return bool(root) and workflows.is_dir() and any(entry.suffix in (".yml", ".yaml")
                                                         for entry in workflows.iterdir())
    except (OSError, subprocess.SubprocessError):
        return False


def folders(calls, last_turn, cwd):
    """The session's folder and each folder a Bash command in last_turn `cd`s into."""
    found = [cwd]
    for turn, name, command, _, _ in calls:
        if turn == last_turn and name == "Bash":
            found += [os.path.normpath(os.path.join(cwd, os.path.expanduser(path.strip("'\""))))
                      for path in re.findall(r"\bcd\s+([^\s;&|)]+)", command)]
    return found


def unwatched_push(calls, last_turn):
    """The last push or PR command in last_turn that no watch covers, or None."""
    watched, opened_since_watch, pending = set(), False, None
    for turn, name, command, failed, output in calls:
        if failed:
            continue
        if name.endswith("unwatch_pull_request"):
            watched.discard(command)
            pending = None
        elif name.endswith("watch_pull_request"):
            watched.add(command)
            opened_since_watch, pending = False, None
        elif name == "Bash":
            code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)  # heredoc bodies are data
            code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
            # In the order the shell runs them, so a push after a merge still counts.
            for match in re.finditer(f"{MERGE.pattern}|{PUSH.pattern}", code):
                if not match.group(1) and not match.group(2):
                    pending = None
                    continue
                if match.group(2) == "ready":
                    # Readying a PR that's already watched opens nothing new.
                    number = READY_PR.match(code, match.end())
                    if not (number and any(key.endswith(f"#{number.group(1)}") for key in watched)):
                        opened_since_watch = True
                elif match.group(2) == "create" or (match.group(1) == "submit" and "Created PR" in output):
                    opened_since_watch = True
                if turn == last_turn:
                    pending = match.group(0)
    if pending and (not watched or opened_since_watch):
        return pending
    return None


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if (event.get("stop_hook_active") or "turn_id" in event or not os.environ.get("T3CODE_CLI_PATH")
            or bare_references.delegated_child(event)):
        return
    try:
        calls, last_turn = tool_calls(event.get("transcript_path"))
        command = unwatched_push(calls, last_turn)
    except (OSError, TypeError, UnicodeDecodeError, RecursionError):
        return
    if not command or not any(has_ci(folder) for folder in folders(calls, last_turn, event.get("cwd") or os.getcwd())):
        return
    feedback = (f"This turn ran `{command}` and no T3 watch is running on that PR, so a failing "
                "check or a review would wait for the user to notice. Call watch_pull_request for "
                "each of the user's PRs you pushed or opened, without asking (replies.md, Waiting). Skip "
                "one that's merged, closed, or someone else's, and say why in a line. T3 shows "
                "only a turn's last message and folds the rest away, so your final reply has to "
                "stand on its own: carry forward what the reply above told the user, adding the watch.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))


if __name__ == "__main__":
    main()

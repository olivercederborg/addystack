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
tool calls in shapes this doesn't read yet.

In a T3 delegated child, it sends the turn back instead when the turn is ending while a
background command (`run_in_background`) or background subagent it started this turn is
still running. A child's parent takes each turn end as the child's result, so it gets a
"still running" note instead of one, even when the task's notification wakes the child later,
as it did in 170 of the 200 fires the 7-day replay found. A brief rule against it failed at
least five times (suite-audit R17, R38, R47, R76, R77; D-r78). It also reads the transcript of each
foreground subagent or forked skill this turn ran, since R77's forked verify-work ended on
its own background test run and handed back "I'll wait for the result notification" as its
verdict. A task counts as finished once a task notification or a TaskStop names it.
`t3_background_wait` doesn't count: it only keeps the thread marked Working, and R76 ended
on its commit after calling it. The send-back says to wait on a command rather than rerun
it, since a second `git commit` started during the first one's pre-commit fails on HEAD's lock. Monitors don't count, since one often outlives the event it
was waiting for. Codex is a no-op: its exec sessions never promise to wake the agent, and
no Codex child was seen ending a turn this way."""
import json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, t3_child, transcripts  # noqa: E402

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


BACKGROUND = re.compile(r"\bbackground with ID: (\w+)")
ASYNC_AGENT = re.compile(r"\AAsync agent launched successfully\..*?\bagentId: (\w+)", re.S)
NOTICE = re.compile(r"<task-notification>\s*<task-id>(\w+)</task-id>")
STOPPED = re.compile(r"\ASuccessfully stopped task: (\w+)")
# A command that serves, such as Metro, a dev preview, or a static server, is meant to outlive
# the turn: in the 7 days to Nov 8, 2026, every such task among the replay's fires.
SERVES = re.compile(r"--port\b|\bhttp\.server\b|\bexpo\s+start\b|\b(?:run(?:\s+--cwd\s+\S+)?|lakebed(?:@\S+)?|next|vite)\s+dev\b")
# A subagent that hands back this many words or more wrote its report, so a task it left
# running isn't one its result waits on. The forks the replay caught handed back 6 to 20
# words, such as R77's "I'll wait for the result notification."; the verdicts, hundreds.
REPORT_WORDS = 40
LONG_LIVED = re.compile(r"^(?:Re)?start\b.*\b(?:server|Metro|preview)\b", re.I)


def entries(path):
    """Each JSON object in a transcript, skipping lines that don't parse."""
    with open(path) as transcript:
        for line in transcript:
            try:
                entry = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(entry, dict):
                yield entry


def notices(entry):
    """The task ids a task notification in this entry names: one queued, consumed, or sent
    as a message, but not one quoted in a tool's output."""
    if entry.get("type") == "queue-operation":
        found = text(entry.get("content"))
    elif entry.get("type") == "attachment":
        found = text((entry.get("attachment") or {}).get("prompt")) if isinstance(entry.get("attachment"), dict) else ""
    elif entry.get("type") == "user" and isinstance(entry.get("message"), dict):
        content = entry["message"].get("content")
        parts = [{"type": "text", "text": content}] if isinstance(content, str) else content
        found = "\n".join(text(part.get("text")) for part in parts if isinstance(part, dict)
                          and part.get("type") == "text") if isinstance(parts, list) else ""
    else:
        found = ""
    return NOTICE.findall(found)


def background_tasks(path, this_turn):
    """(started, finished, forks) for a transcript. started maps each background task id
    to (what it runs, whether it serves), finished holds every task id a notification or
    TaskStop names, and forks lists (agent id, name, what it handed back) for each foreground
    subagent or forked skill that returned. this_turn counts only starts and forks after the
    last Stop hook run."""
    started, finished, forks, uses = {}, set(), [], {}
    for entry in entries(path):
        if this_turn and entry.get("type") == "system" and entry.get("subtype") == "stop_hook_summary":
            started, forks = {}, []
        finished.update(notices(entry))
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                tool_input = part.get("input") if isinstance(part.get("input"), dict) else {}
                command, about = text(tool_input.get("command")), text(tool_input.get("description"))
                uses[text(part.get("id"))] = (text(part.get("name")), about or command[:60] or text(tool_input.get("skill")),
                                              text(tool_input.get("skill")), bool(SERVES.search(command) or LONG_LIVED.search(about)))
            elif part.get("type") == "tool_result":
                name, label, skill, serves = uses.get(text(part.get("tool_use_id")), ("", "", "", False))
                output = part.get("content")
                output = output if isinstance(output, str) else "\n".join(
                    text(item.get("text")) for item in output if isinstance(item, dict)) if isinstance(output, list) else ""
                if stopped := STOPPED.match(output):
                    finished.add(stopped.group(1))
                elif (launched := BACKGROUND.search(output) if name == "Bash" else ASYNC_AGENT.match(output)
                      if name in ("Agent", "Task") else None):
                    started[launched.group(1)] = (label or launched.group(1), serves)
                elif isinstance(entry.get("toolUseResult"), dict) and name in ("Agent", "Task", "Skill"):
                    result = entry["toolUseResult"]
                    if agent := text(result.get("agentId")):
                        forks.append((agent, skill or label, text(result.get("result")) or "\n".join(
                            text(item.get("text")) for item in result.get("content") or [] if isinstance(item, dict))
                            if isinstance(result.get("content") or [], list) else ""))
    return started, finished, forks


def unfinished(path, session_id):
    """What each background task this turn started runs, oldest first, as "`label`", when no
    notification or TaskStop ended it and it doesn't serve, including those a foreground
    subagent or forked skill left running when it returned."""
    started, finished, forks = background_tasks(path, this_turn=True)
    found = [(task, f"`{label}`", serves) for task, (label, serves) in started.items()]
    for n, (agent, name, handed_back) in enumerate(forks):
        fork = Path(path).parent / str(session_id) / "subagents" / f"agent-{agent}.jsonl"
        # A later run of the same skill or subagent replaces this one's result.
        if not re.fullmatch(r"\w+", agent) or not fork.is_file() or any(later[1] == name for later in forks[n + 1:]):
            continue
        inner, done, _ = background_tasks(fork, this_turn=False)
        finished |= done
        if len(handed_back.split()) >= REPORT_WORDS:
            continue
        found += [(task, f"`{label}` in {name or 'a subagent'}'s run", serves) for task, (label, serves) in inner.items()]
    return [label for task, label, serves in found if task not in finished and not serves]


def background_feedback(event):
    """The send-back for a delegated child's turn that ends on its own unfinished
    background work, or None."""
    try:
        left = unfinished(event.get("transcript_path"), event.get("session_id"))
    except (OSError, TypeError, UnicodeDecodeError, RecursionError):
        return None
    if not left:
        return None
    return (f"Your turn is ending while background work started this turn is still running: {', '.join(left)}. "
            "Your parent takes each turn end as your result, even if that work wakes you later, so wait for it "
            "before ending the turn: check a command's output file or pid in counted loops whose sleeps add up "
            "to under 2 minutes each, without starting it again, and run a subagent's work again in the "
            "foreground, since its run is over (`t3_background_wait` only keeps the thread marked Working).")


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active") or "turn_id" in event:
        return
    if bare_references.delegated_child(event):
        # Only T3's database names a child here: a top-level thread whose first prompt reads like
        # a brief may leave background work running.
        if t3_child.delegated_brief(event.get("session_id")) is not None and (feedback := background_feedback(event)):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))
        return
    if not os.environ.get("T3CODE_CLI_PATH"):
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

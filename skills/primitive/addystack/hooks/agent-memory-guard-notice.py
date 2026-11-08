#!/usr/bin/env python3
"""PostToolUseFailure on Bash: when agent_memory_guard.py killed this command, tell the
agent why. The guard SIGKILLs the whole command, wrapper shell included, so the agent
otherwise sees exit 1 with no output and tends to rerun it as is.

A log entry is this run's kill when its full-command hash matches, it was logged while
the command ran, and the agent it names is an ancestor of this hook, so another
session's kill of the same command can't match. Each kill is reported once, so a quick
retry of the same command can't reuse it. Known limit: two identical commands running at
once in one session, one killed and one failing on its own, can get each other's."""
import hashlib, json, os, subprocess, sys, time

LOG = os.path.expanduser("~/Library/Logs/agent-memory-guard.log")
REPORTED = os.path.expanduser("~/Library/Logs/agent-memory-guard.reported")  # kill times


def ancestors():
    out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout
    parents = dict(map(int, line.split()) for line in out.splitlines())
    pid, seen = os.getpid(), set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        pid = parents.get(pid, 0)
    return seen


payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")
digest = hashlib.sha256(command.encode()).hexdigest()
# One second covers the gap between Claude Code's timer and the guard's clock read.
started = time.time() - (payload.get("duration_ms") or 0) / 1000 - 1
try:
    with open(LOG) as log:
        lines = log.readlines()[-50:]
except OSError:
    sys.exit(0)
try:
    with open(REPORTED) as reported:
        done = set(reported.read().split())
except OSError:
    done = set()

mine = None
for line in reversed(lines):
    try:
        entry = json.loads(line)
        if (entry["command_sha256"] != digest or entry["at"] < started
                or repr(entry["at"]) in done):
            continue
    except (ValueError, KeyError, TypeError):
        continue  # a partial or older-format line
    mine = ancestors() if mine is None else mine
    if entry.get("agent_pid") in mine:
        try:
            with open(REPORTED, "a") as reported:
                reported.write(repr(entry["at"]) + "\n")
        except OSError:
            pass  # the notice matters more than deduplicating it
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUseFailure",
            "additionalContext": f"agent-memory-guard killed this command ({entry['reason']}) "
                                 "so it wouldn't freeze the Mac. Don't rerun it as is: lower "
                                 "its parallelism or memory use, or split it up.",
        }}))
        break

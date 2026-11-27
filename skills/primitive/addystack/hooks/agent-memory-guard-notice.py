#!/usr/bin/env python3
"""Everything agent_memory_guard.py tells an agent, by the payload's hook_event_name, all on
Bash under one manifest id, so the guard and its messages are selected together:

- PreToolUse (Claude and Codex): while the guard's check queue holds a check, say how
  many, so the agent waits for a check that prints nothing instead of killing or rerunning
  it. Nothing else, and no permission decision.
- PostToolUseFailure (Claude; a payload without the field counts as one): when the guard
  killed this command, say why. The guard SIGKILLs the whole command, wrapper shell
  included, or a queued check's processes, so the agent otherwise sees a failure with no
  output and tends to rerun it as is.
- PostToolUse (Codex, which has no failure event and runs it after every Bash call, a
  yielded command's when a later poll sees it end): the same, for the kill whose
  tool_call_id, the CODEX_TOOL_CALL_ID the guard read from the command's environment, is
  this call's tool_use_id.

In Claude, a log entry is this run's kill when its full-command hash matches, it was logged
while the command ran, and the agent it names is an ancestor of this hook, so another
session's kill of the same command can't match. Each kill is reported once, so a quick
retry of the same command can't reuse it. Known limit: two identical Claude commands
running at once in one session, one killed and one failing on its own, can get each
other's. Only the log's last TAIL_BYTES are read, so a kill buried under more queue lines
than that goes unreported."""
import hashlib, json, os, subprocess, sys, time

LOG = os.path.expanduser("~/Library/Logs/agent-memory-guard.log")
REPORTED = os.path.expanduser("~/Library/Logs/agent-memory-guard.reported")  # kill times
QUEUE = os.path.join(os.path.expanduser(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")),
                     "check-queue.json")
TAIL_BYTES = 256 * 1024
HOLD_MINUTES = 15
# What to do next, by the kill's rule; a memory or CPU kill has none.
ADVICE = {
    "queue": "Don't rerun it as is: wait for other agents' checks to finish, or run a narrower "
             "check, such as one package.",
    None: "Don't rerun it as is: lower its parallelism or memory use, or split it up.",
}


def queued():
    """How many checks the guard holds, or 0 when its queue file can't be read."""
    try:
        with open(QUEUE) as file:
            held = json.load(file)["held"]
        return len(held) if isinstance(held, list) else 0
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def kills():
    """The kill lines in the log's last TAIL_BYTES, newest first. Lines with an `event`
    are the check queue's stops and resumes."""
    try:
        with open(LOG, "rb") as log:
            log.seek(max(0, os.fstat(log.fileno()).st_size - TAIL_BYTES))
            lines = log.read().decode(errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and "event" not in entry and isinstance(entry["at"], (int, float)):
                found.append(entry)
        except (ValueError, KeyError, TypeError):
            continue  # a partial or older-format line
    return found


def ancestors():
    out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout
    parents = dict(map(int, line.split()) for line in out.splitlines())
    pid, seen = os.getpid(), set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        pid = parents.get(pid, 0)
    return seen


def notice(entry):
    if entry.get("rule") == "queue":
        what = (f"agent-memory-guard killed this command's check after it waited {HOLD_MINUTES} min "
                f"while the machine's check queue stayed full ({entry['reason']}).")
    else:
        what = f"agent-memory-guard killed this command ({entry['reason']}) so it wouldn't freeze the Mac."
    return f"{what} {ADVICE.get(entry.get('rule'), ADVICE[None])}"


def main():
    payload = json.load(sys.stdin)
    event = payload.get("hook_event_name") or "PostToolUseFailure"
    if event == "PreToolUse":
        count = queued()
        if count:
            checks = "1 check is" if count == 1 else f"{count} checks are"
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"agent-memory-guard: {checks} queued behind other agents' checks. "
                                     f"A type check, lint, or test you start now may wait silently for up "
                                     f"to {HOLD_MINUTES} min, and is killed if the queue is still full "
                                     "then. Don't kill or rerun a check that prints nothing; wait for it.",
            }}))
        return
    try:
        with open(REPORTED) as reported:
            done = set(reported.read().split())
    except OSError:
        done = set()
    found = [entry for entry in kills() if repr(entry["at"]) not in done]
    if event == "PostToolUse":
        call = payload.get("tool_use_id")
        mine = [entry for entry in found if call and entry.get("tool_call_id") == call]
    else:
        command = (payload.get("tool_input") or {}).get("command", "")
        digest = hashlib.sha256(command.encode()).hexdigest()
        # One second covers the gap between Claude Code's timer and the guard's clock read.
        started = time.time() - (payload.get("duration_ms") or 0) / 1000 - 1
        mine = [entry for entry in found if entry.get("command_sha256") == digest and entry["at"] >= started]
        if mine:
            family = ancestors()
            mine = [entry for entry in mine if entry.get("agent_pid") in family]
    if not mine:
        return
    try:
        with open(REPORTED, "a") as reported:
            reported.writelines(repr(entry["at"]) + "\n" for entry in mine)
    except OSError:
        pass  # the notice matters more than deduplicating it
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": notice(mine[0])}}))


if __name__ == "__main__":
    main()

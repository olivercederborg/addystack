#!/usr/bin/env python3
"""PreToolUse on Bash: deny a foreground command that holds the turn polling for something
that can take minutes, and point at run_in_background, Monitor, or watch_pull_request.
Denies `until`/`while` loops that sleep, counted `for` loops whose sleeps add up to more
than the Bash tool's 2-minute default timeout, `sleep N` of a minute or more, and
`gh pr checks --watch` / `gh run watch`. Short sleeps such as waiting a second for a port,
and `while read` loops that pause between items, stay allowed. Added after 107 such commands in 43 sessions, counted from
transcripts (Sep 17 to Oct 9, 2026).

In a T3 delegated child it points at counted loops instead, since the parent takes each of a
child's turn ends as its result, so a child can't end its turn to wait on a background task.

Known limit: loops written inside a script file or heredoc that the command runs aren't
seen."""
import json, re, sys
from pathlib import Path

payload = json.load(sys.stdin)
tool_input = payload.get("tool_input") or {}
if tool_input.get("run_in_background"):
    sys.exit(0)
command = tool_input.get("command", "")

code = re.sub(r"<<-?\s*(['\"])(\w+)\1.*?\n.*?\n\2\b", "", command, flags=re.S)
code = re.sub(r"'[^']*'", "''", code)

LIMIT = 120


def sleeps(text):
    return [float(s) for s in re.findall(r"\bsleep\s+(\d+(?:\.\d+)?)\b", text)]


def counted_loop_seconds(text):
    for match in re.finditer(r"\bfor\s+\w+\s+in\s+(.*?);?\s*do\b(.*?)\bdone\b", text, flags=re.S):
        items, body = match.groups()
        bounds = (re.search(r"\$\(\s*seq\s+(?:(\d+)\s+)?(\d+)\s*\)", items)
                  or re.search(r"\{(\d+)\.\.(\d+)\}", items))
        if bounds:
            start, end = bounds.groups()
            count = int(end) - int(start or 1) + 1
        else:
            count = len(items.split())
        yield count * sum(sleeps(body))


reason = None
if re.search(r"\bgh\s+pr\s+checks\b[^;&|]*--watch\b|\bgh\s+run\s+watch\b", code):
    reason = "`gh … watch` holds the turn until CI finishes"
elif any(sleeps(body) for body in re.findall(r"\b(?:until|while)\b(?!\s+(?:IFS=\S*\s+)?read\b).*?\bdo\b(.*?)\bdone\b",
                                             code, flags=re.S)):
    reason = "a sleeping `until`/`while` loop holds the turn with no upper bound"
elif any(seconds > LIMIT for seconds in counted_loop_seconds(code)):
    reason = f"this loop can sleep for more than {LIMIT} seconds"
elif any(seconds >= 60 for seconds in sleeps(code)):
    reason = "a sleep of a minute or more holds the turn"

if not reason:
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_child  # noqa: E402

if t3_child.delegated_brief(payload.get("session_id")) is not None:
    # A child's parent takes each turn end as its result, so pr_watch.py sends back a turn that
    # ends on background work; R76's child moved its commit to the background on this advice.
    advice = ("Wait in counted loops whose sleeps add up to under 2 minutes each, such as "
              "`for i in $(seq 11); do kill -0 <pid> 2>/dev/null || break; sleep 10; done`, and repeat "
              "until it's done. Your parent takes each turn end as your result, so don't end the turn "
              "to wait on a background task.")
else:
    advice = ("Run it with `run_in_background: true`, which re-invokes you when it exits; use the Monitor "
              "tool to wait for a line in a log or file; or, for a PR's CI and reviews, use T3's "
              "`watch_pull_request`. Keep working on independent steps meanwhile.")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": f"{reason}. {advice}",
}}))

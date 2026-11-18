#!/usr/bin/env python3
"""PreToolUse on Bash: deny a foreground command that holds the turn polling for something
that can take minutes, and point at run_in_background, Monitor, or watch_pull_request.
Denies `until`/`while` loops that sleep, unless bash-rewrite.py gives each a time limit
(shell_syntax.py says which it does), counted `for` loops whose sleeps add up to more
than the Bash tool's 2-minute default timeout, `sleep N` of a minute or more, and
`gh pr checks --watch` / `gh run watch`. Short sleeps such as waiting a second for a port,
and `while read` loops that pause between items, stay allowed. Added after 107 such commands in 43 sessions, counted from
transcripts (Sep 17 to Oct 9, 2026).

In a T3 delegated child it points at counted loops instead, since the parent takes each of a
child's turn ends as its result, so a child can't end its turn to wait on a background task.
So does a work-verifier fork, since its background work stops when it hands back: on Nov 7,
2026, verify-102-2's fork took this hook's run_in_background advice for its build and handed
back without a verdict. The rules live in shell_syntax.held, which bash-rewrite.py also
reads for a verifier's background call it moves to the foreground.

Known limit: loops written inside a script file or heredoc that the command runs aren't
seen."""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shell_syntax, t3_child  # noqa: E402

payload = json.load(sys.stdin)
tool_input = payload.get("tool_input") or {}
if tool_input.get("run_in_background"):
    sys.exit(0)
command = tool_input.get("command", "")


def rewrite_installed():
    """Whether Claude Code's settings run bash-rewrite.py before Bash, so its guard applies."""
    home = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    settings = (Path(os.path.abspath(home)) if home else Path("~/.claude").expanduser()) / "settings.json"
    try:
        groups = json.loads(settings.read_text())["hooks"]["PreToolUse"]
        return any("bash-rewrite.py" in hook.get("command", "") for group in groups
                   if group.get("matcher") in (None, "", "*") or re.fullmatch(group["matcher"], "Bash")
                   for hook in group["hooks"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, re.error):
        return False


reason = shell_syntax.held(command, tool_input.get("timeout"), rewrite_installed)
if not reason:
    sys.exit(0)

if t3_child.holds_turn(payload):
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

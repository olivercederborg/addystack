#!/usr/bin/env python3
"""PostToolUse and PostToolUseFailure on Bash: when a command's output shows the SSH
agent refusing to sign (1Password locked, or waiting for approval), say so instead of
letting the agent retry a push that looks like a GitHub outage. Added after a push failed
with `sign_and_send_pubkey: signing failed` and the agent retried with sleeps (Oct 2026).
A failed command only reaches PostToolUseFailure, with its output in `error`.

Known limits, since regexes can't parse shell: git global options other than `-c` and
`-C` before the subcommand, and a signing command that runs only inside quotes
(`bash -c 'git push'`)."""
import json, re, sys

payload = json.load(sys.stdin)
# Only commands that sign or reach a remote can hit the agent. A read that prints the
# message (`git diff`, `gh pr diff`, `cat` of this file) can't.
command = (payload.get("tool_input") or {}).get("command", "")
# Quoted text and heredoc bodies are data (`git log --grep='git push'`), not commands.
command = re.sub(r"([^\n]*<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2\b", r"\1", command, flags=re.S)
command = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", command)
signs = (r"(?:^|[\s;&|(])(?:\S*/)?(?:git(?:\s+-[cC]\s+\S+)*\s+(?:commit|push|pull|fetch|clone|tag|merge"
         r"|rebase|cherry-pick|revert|am|ls-remote|submodule)|gt|ssh|scp|rsync|yadm|gh\s+(?:repo\s+clone|stack))(?=[\s);&|]|$)")
if not re.search(signs, command):
    sys.exit(0)
response = payload.get("tool_response") or {}
text = response if isinstance(response, str) else " ".join(
    str(response.get(key, "")) for key in ("stdout", "stderr", "output"))
text += " " + str(payload.get("error") or "")
if not re.search(r"sign_and_send_pubkey|communication with agent failed|agent refused operation", text):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": payload.get("hook_event_name", "PostToolUse"),
    "additionalContext": "SSH signing is blocked by the SSH agent (likely 1Password locked or "
                         "waiting for approval), not a GitHub outage. Don't retry or wait: ask "
                         "the user to unlock or approve 1Password, then retry once.",
}}))

#!/usr/bin/env python3
"""PreToolUse on Bash: passes a `work-verifier` subagent's identity to record-verdict.sh,
which refuses any caller without it. Only hook input names a subagent (`agent_id`,
`agent_type`); its shell shares the parent's session ID."""
from __future__ import annotations

import json
import shlex
import sys


def rewrite_recording(payload: dict) -> dict | None:
    """An updatedInput that sets verdicts.HOOK_CONTEXT on a verifier's command that names
    record-verdict.sh; None otherwise. No shell parsing: an extra variable is harmless."""
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command", "")
    if "record-verdict.sh" not in command or not payload.get("agent_id"):
        return None
    from verdicts import HOOK_CONTEXT, VERIFIER  # here, so a broken verdicts.py blocks only recording
    if payload.get("agent_type") != VERIFIER:
        return None
    identity = json.dumps({"session_id": payload.get("session_id", ""),
                           "agent_id": payload["agent_id"], "agent_type": VERIFIER})
    return {"hookEventName": "PreToolUse", "updatedInput": {
        **tool_input, "command": f"export {HOOK_CONTEXT}={shlex.quote(identity)}; {command}"}}


if __name__ == "__main__":
    output = rewrite_recording(json.load(sys.stdin))
    if output:
        print(json.dumps({"hookSpecificOutput": output}))

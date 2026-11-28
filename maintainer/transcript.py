"""Reads session transcripts for the eval runner (evals.py) and run_cost.py: their JSONL
records, a Claude Code session's events and the skills it loaded, which user lines the
harness injected, and a Codex rollout's session id. Python 3.9+, stdlib only.
"""
import json
import os
import re
from pathlib import Path

# Messages Claude Code or T3 injects as user turns in a Claude Code session. Unknown tags
# stay user turns, and so do the user's own input in tags: slash commands (<command-name>)
# and answers to questions (<send_user_message_question_reply>).
INJECTED = re.compile(
    r"^\s*<(system-reminder|task-notification|app-context|local-command-stdout"
    r"|local-command-caveat|external_[a-z_]+|heartbeat)[\s>]")
BASE_DIRECTORY = "Base directory for this skill: "


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block_text(b.get("text") or b.get("content") or "") if isinstance(b, dict)
                         else block_text(b) for b in content)
    return ""


def records(path):
    """Each JSON line with its line number."""
    with open(path, "rb") as f:
        for number, raw in enumerate(f, 1):
            try:
                yield number, json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue


def claude_events(path):
    for number, r in records(path):
        line = f"L{number}"
        if r.get("type") not in ("user", "assistant") or r.get("isSidechain"):
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content or []:
            kind = b.get("type")
            if kind == "text":
                # isMeta marks harness-injected user text, such as a loaded skill's body;
                # isCompactSummary marks the summary written after a compaction.
                injected = r.get("isMeta") or r.get("isCompactSummary")
                yield line, "meta" if injected else r["type"], b.get("text", "")
            elif kind == "tool_use":
                yield line, "tool", (b.get("name"), b.get("input"))
            elif kind == "tool_result":
                yield line, "error" if b.get("is_error") else "result", block_text(b.get("content"))


def session_meta(path):
    for _, r in records(path):
        return (r.get("payload") or {}) if r.get("type") == "session_meta" else {}
    return {}


def codex_session_id(path):
    # A subagent's session_id is its parent's; its own id is `id`.
    return session_meta(path).get("id")


def is_codex(path):
    with open(path, errors="replace") as f:
        first = f.readline()
    return '"session_meta"' in first or Path(path).name.startswith("rollout-")


def is_injected(text):
    return bool(INJECTED.match(text))


def skills(path):
    """The names of the skills a Claude Code session loaded, in name order: each one whose
    body the harness injected through its "Base directory" row after a Skill call, named by
    the folder its SKILL.md resolves into, and each Skill call with no body, such as a built-in or
    a skill whose files moved."""
    loaded, called = set(), set()
    for _, role, payload in claude_events(path):
        if role == "meta" and payload.startswith(BASE_DIRECTORY):
            folder = os.path.expanduser(payload[len(BASE_DIRECTORY):].split("\n")[0].strip())
            skill = os.path.join(folder, "SKILL.md")
            if os.path.isfile(skill):
                loaded.add(os.path.basename(os.path.dirname(os.path.realpath(skill))))
        elif role == "tool" and payload[0] == "Skill" and isinstance(payload[1], dict) and payload[1].get("skill"):
            called.add(payload[1]["skill"].rsplit(":", 1)[-1])  # "plugin:skill" loads as "skill"
    return sorted(loaded | called)

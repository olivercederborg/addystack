"""The T3 tool results of the router's current turn, read from its own Claude Code
transcript, so no agent copies a tool's output by hand.

A shell can't call T3's MCP itself: `/mcp` takes only an OAuth credential granted in a
browser, and a `t3 auth session` bearer token gets `invalid_mcp_credential`. But Claude Code
writes every tool result to the session's transcript, and puts a result too big for the
model's context in a tool-results file, leaving its path in the transcript. The transcript
can lag a call; a result not there yet reads as a call still to make, so the worst case
is one repeated call. This module reads both, for the session in CLAUDE_CODE_SESSION_ID
(CHIEF_TRANSCRIPT names a transcript file instead).

A turn starts at the newest prompt: a user entry that holds text, not a tool result, and
isn't a meta entry or a compaction summary, so a compaction mid-run keeps the calls made
before it. A subagent's entries (isSidechain) are its own, not the router's."""
from __future__ import annotations

import glob, json, os, re
from dataclasses import dataclass
from pathlib import Path

PROJECTS = os.environ.get("CHIEF_CLAUDE_PROJECTS", "~/.claude/projects")
# Claude Code's note for a result it saved to a file instead of the context.
SAVED = re.compile(r"saved to (/\S+)")


class Unavailable(RuntimeError):
    """No transcript to read: not run from a Claude Code session, or its file is missing."""


@dataclass
class Call:
    tool: str  # the T3 tool's name, such as t3_thread_list
    args: dict
    result: object = None  # the parsed JSON result, or None with an error
    error: str | None = None


def transcript_path(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    if environ.get("CHIEF_TRANSCRIPT"):
        return Path(environ["CHIEF_TRANSCRIPT"]).expanduser()
    session = environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        raise Unavailable("no CLAUDE_CODE_SESSION_ID; run it from the chief router's Claude Code session")
    found = sorted(glob.glob(str(Path(PROJECTS).expanduser() / "*" / f"{session}.jsonl")), key=os.path.getmtime)
    if not found:
        raise Unavailable(f"no transcript for session {session} under {PROJECTS}")
    return Path(found[-1])


def turn_calls(path) -> list[Call]:
    """Each T3 tool call of the current turn that has a result, in call order."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise Unavailable(f"can't read the transcript {path}: {error.strerror}") from None
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue  # a line still being written
    start = 0
    for at, entry in enumerate(entries):
        if is_prompt(entry):
            start = at
    uses, calls = {}, []
    for entry in entries[start:]:
        if entry.get("isSidechain"):
            continue
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and t3_tool(part.get("name")):
                uses[part.get("id")] = (t3_tool(part.get("name")), part.get("input") or {})
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in uses:
                tool, args = uses.pop(part["tool_use_id"])
                calls.append(outcome(tool, args, part))
    return calls


def is_prompt(entry) -> bool:
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return False
    if entry.get("isMeta") or entry.get("isCompactSummary") or entry.get("isVisibleInTranscriptOnly"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    kinds = {part.get("type") for part in content if isinstance(part, dict)}
    return "text" in kinds and "tool_result" not in kinds


def t3_tool(name) -> str | None:
    """`t3_thread_list` for `mcp__t3-code__t3_thread_list`, else None."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return None
    tool = name.rsplit("__", 1)[-1]
    return tool if tool.startswith("t3_") else None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""


def outcome(tool, args, part) -> Call:
    text = text_of(part.get("content")).strip()
    if part.get("is_error"):
        return Call(tool, args, error=first_line(text) or "the call failed")
    saved = SAVED.search(text[:600]) if not text.startswith(("{", "[")) else None
    if saved:
        location = saved.group(1).rstrip(".,;")
        try:
            text = Path(location).read_text(encoding="utf-8")
        except OSError as error:
            return Call(tool, args, error=f"can't read its saved result {location}: {error.strerror}")
    try:
        return Call(tool, args, result=json.loads(text))
    except ValueError:
        return Call(tool, args, error=first_line(text) or "an empty result")


def first_line(text) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")[:200]

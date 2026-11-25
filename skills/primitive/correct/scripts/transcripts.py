# Copy of skills/primitive/addystack/hooks/transcripts.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""Reads the user's own messages from a Claude Code or Codex transcript, oldest first,
each with the assistant reply it answered.

Claude Code writes `"type": "user"` entries, whose content is a string or a list of
parts. Codex writes `response_item` messages with `role: "user"` and `input_text`
parts. Both also carry text the user didn't type: tool results, meta entries,
compaction summaries, AGENTS.md and environment context, attachment tags, interrupt
markers, T3's child-task notices, and messages another thread sent, which T3's state
database marks as sent by an agent (t3_child.py). Those are dropped
part by part, so the last message is the one the user sent, with every word they typed.
A slash command reads as the command and its arguments, except one Claude Code runs
itself, such as /compact or /model, which it marks by writing the command's output as a
`<local-command-stdout>` message right after it: no turn answers it, so both are dropped.
A T3 quote, review comment, or
preview annotation reads as the comment the user wrote on it: a quote link carries it in
its `comment` parameter, and the context T3 appends after the message in a `comment:`
field, a `Comment:` line, or a citation's `comment`. The rest of that context, such as
terminal output, page elements, diffs, a PR chip's description, and a captured window's
data, is dropped.

A reply is the assistant's text: Claude Code's `"type": "assistant"` entries with `text`
parts, one entry per part, and Codex's `response_item` messages with `role: "assistant"`
and `output_text` parts, whose commentary comes before the final answer."""
import json, pathlib, re
from typing import NamedTuple, Optional
from urllib.parse import parse_qs, urlparse

import t3_child

NOT_TYPED = ("<", "[T3 Code: ", "# AGENTS.md", "Context handoff", "[Historical user", "Delegated task node:",
             "This session is being continued", "Caveat:", "Update on pull request")
ATTACHMENT = re.compile(r"\[(?:Attached image|Image|Terminal|User attached|Request interrupted)[^\]]*\]")
QUOTE = re.compile(r"\[Assistant quote\]\((t3-citation://[^)\s]*)\)")
COMMAND = re.compile(r"<command-name>(.*?)</command-name>(?:.*?<command-args>(.*?)</command-args>)?", re.S)
APPENDED = re.compile(r"<(t3_context|assistant_citations|preview_annotation|terminal_context|element_context)"
                      r"\b[^>]*>.*?</\1>", re.S)
# T3's server writes a review comment as "comment:" with the text indented below, and a
# preview annotation as "comment: <text>", whose later lines run to the next field. Its
# older formatter wrote "Comment: <text>" the same way.
COMMENT = re.compile(r"(?i)^comment:[ \t]*(.*)$")
NEXT_FIELD = re.compile(r"(?i)^(?:targets: |requested visual changes:|screenshot: ref=|element \d+:$|"
                        r"<element_context>|</|[a-z]+:$)")
# A PR chip is a review-comment record on "PR #N" whose comment is T3's description of the PR.
PR_REFERENCE = re.compile(r'<context kind="review-comment"[^>]*>\nfile: PR #\d+\n.*?</context>', re.S)
# A captured window's accessibility data, which T3 adds after a window screenshot.
WINDOW = re.compile(r"Untrusted captured-window data follows as JSON\..*?End untrusted captured-window data\.", re.S)
# T3's inline labels for what it appends: "[assistant-quote-1]", "[Review comment: …; ref=…]".
MARKER = re.compile(r"\[(?:assistant-quote-\d+|[A-Z][A-Za-z ]{1,30}: [^\]\n]*; ref=[^\]\n]*)\]")
# "From the Platform lane (…): …", "From the orchestrator: …", sent by t3_thread_send, for
# a transcript T3's state database doesn't know.
# The line T3 puts before a message an agent, a tool, or a scheduled task sent, never before
# one the user typed (withMessageSenderNote). Its database stores the text without it.
SENDER_NOTE = re.compile(r"\[T3 Code: [^\]\n]*\]\n\n")
OTHER_THREAD = re.compile(r"From the [^:.\n]{0,80}?\b(?:lane|thread|orchestrator)\b")


def comment(match):
    try:
        return parse_qs(urlparse(match.group(1)).query).get("comment", [""])[0]
    except ValueError:  # a malformed link, such as "t3-citation://[x", carries no comment
        return ""


def appended_comments(match):
    """The user's comments in a block T3 appends, without the code or text they're on."""
    block = PR_REFERENCE.sub("", match.group(0))
    if match.group(1) != "assistant_citations":
        found = comment_fields(block)
    else:
        try:
            start = re.search(r"^\[", block, re.M).start()
            citations = json.loads(block[start:block.rindex("]") + 1])
            found = [(item.get("citation") or {}).get("comment") or "" for item in citations]
        except (ValueError, AttributeError, TypeError):
            found = []
    return "\n".join(text for text in found if isinstance(text, str) and text)


def comment_fields(block):
    """Each comment field in a context block, its lines joined into one. A bare "comment:"
    holds only the indented lines below it, since the snippet's heading after them is its
    file's language, such as "json5:"."""
    found, lines = [], block.splitlines()
    for at, line in enumerate(lines):
        if match := COMMENT.match(line):
            words = [match.group(1)]
            for rest in lines[at + 1:]:
                if NEXT_FIELD.match(rest) if match.group(1) else not rest[:1].isspace():
                    break
                words.append(rest)
            found.append(" ".join(" ".join(words).split()))
    return found


FLAGS = ("isMeta", "isCompactSummary", "isSidechain")


def text_parts(entry):
    """A prompt's content as a list of parts, or None for a well-formed entry that isn't
    one: another type, a meta entry, a compaction summary, or a sidechain. Any other line,
    such as `null`, a user entry whose message isn't an object, or a flag that isn't a
    boolean, has no parts, so it still counts as a prompt the user didn't type and an
    earlier go doesn't stand."""
    if not isinstance(entry, dict) or not isinstance(entry.get("type"), str) \
            or not all(isinstance(entry.get(flag, False), bool) for flag in FLAGS):
        return []
    if any(entry.get(flag) for flag in FLAGS):
        return None
    if entry["type"] == "user":
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
    elif entry["type"] == "response_item":
        payload = entry.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str) \
                or not isinstance(payload.get("role", ""), str):
            return []
        if payload["type"] != "message" or payload.get("role") != "user":
            return None
        content = payload.get("content")
    else:
        return None
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def texts(content):
    return [text if isinstance(text := part.get("text", ""), str) else "" for part in content
            if isinstance(part, dict) and part.get("type") in ("text", "input_text")]


def prompt_text(entry):
    """For a prompt, the text the user typed in it, "" when they typed none; None for an
    entry that isn't one (text_parts) or a tool result."""
    content = text_parts(entry)
    if content is None or any(isinstance(part, dict) and part.get("type") == "tool_result" for part in content):
        return None
    return " ".join(text for text in map(typed, texts(content)) if text)


def reply_text(entry):
    """For an assistant message, its text, None for any other entry or one with no text.
    A sidechain's, or one with a flag that isn't false, isn't the thread's reply."""
    if not isinstance(entry, dict) or any(entry.get(flag, False) is not False for flag in FLAGS):
        return None
    if entry.get("type") == "assistant":
        message, part_type = entry.get("message"), "text"
        content = message.get("content") if isinstance(message, dict) else None
    elif entry.get("type") == "response_item":
        payload, part_type = entry.get("payload"), "output_text"
        if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "assistant":
            return None
        content = payload.get("content")
    else:
        return None
    if isinstance(content, str):
        content = [{"type": part_type, "text": content}]
    parts = [part.get("text") for part in content if isinstance(part, dict) and part.get("type") == part_type] \
        if isinstance(content, list) else []
    text = "\n".join(part for part in parts if isinstance(part, str))
    return text if text.strip() else None


# What Claude Code records for a Stop a hook continued: a `decision: block` and additionalContext.
# A hook's non-blocking error (hook_non_blocking_error) lands in the same summary's hookErrors
# but ends the turn as any Stop does.
CONTINUED = ("hook_blocking_error", "hook_additional_context")


def entries(path):
    """The Claude Code transcript at path, a parsed record per line it can parse; raises OSError."""
    out = []
    with open(path) as transcript:
        for line in transcript:
            try:
                out.append(json.loads(line))
            except (ValueError, RecursionError):
                continue
    return out


# How Claude Code records a turn the user stopped, with no Stop: a message, or, during a tool call,
# only the call's tool_result ("[Request interrupted by user for tool use]").
INTERRUPTED = "[Request interrupted by user"


def said(parts):
    """The text in a message's parts and in its tool results' content."""
    out = texts(parts)
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "tool_result":
            content = part.get("content")
            out += [content] if isinstance(content, str) else texts(content) if isinstance(content, list) else []
    return out


def stops(found):
    """Each turn boundary in found, a transcript's entries, by position: "continued" at a
    Stop's stop_hook_summary record when a hook continued the turn there (a CONTINUED record
    for that Stop's toolUseID), "ended" at one that ended the turn, and "interrupted" at the
    record of a turn the user interrupted, which ends it without a Stop."""
    continued = {part.get("toolUseID") for entry in found if isinstance(entry, dict)
                 and isinstance(part := entry.get("attachment"), dict) and part.get("type") in CONTINUED}
    out = {}
    for at, entry in enumerate(found):
        if isinstance(entry, dict) and entry.get("type") == "system" and entry.get("subtype") == "stop_hook_summary":
            out[at] = "continued" if entry.get("toolUseID") in continued else "ended"
        elif any(text.startswith(INTERRUPTED) for text in said(text_parts(entry) or [])):
            out[at] = "interrupted"
    return out


def entry_text(entry):
    """The typed text an entry carries, or None for anything the user didn't type."""
    return prompt_text(entry) or None


def typed(text):
    """What the user typed in one text part, or "" for an injected one."""
    if command := COMMAND.search(text) if text.lstrip().startswith("<command-") else None:
        name, args = command.groups()
        return " ".join(part for part in (name.strip(), typed(args or "")) if part)
    text = APPENDED.sub(appended_comments, MARKER.sub("", WINDOW.sub("", text)))
    text = QUOTE.sub(comment, ATTACHMENT.sub("", text)).strip()
    return "" if text.startswith(NOT_TYPED) or OTHER_THREAD.match(text) else text


# A session's id ends its file name: `<id>.jsonl` in Claude Code, `rollout-<time>-<id>.jsonl` in Codex.
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def agent_sent(senders, seen, text):
    """True when this copy of text is one an agent sent: the nth copy in a transcript pairs
    with the nth message with that text in t3_child.senders, and one past the last repeats
    the last sender. seen counts the copies so far, per text."""
    if text not in senders:
        return False
    seen[text] = seen.get(text, -1) + 1
    creators = senders[text]
    return creators[min(seen[text], len(creators) - 1)] == "agent"


class Exchange(NamedTuple):
    reply: Optional[str]  # the last assistant text since the prompt before; None if there's none
    prompt: str  # as prompts() gives it
    agent: bool = False  # T3's state database says only other agents ever sent its text


def exchanges(path, strict=False):
    """Each prompt in the transcript at path, oldest first, with the reply it answered: the
    last assistant text after the prompt before it. Tool results and meta entries aren't
    prompts, so a turn's last text is its reply; an interrupted turn with no text, or the
    turn a queued prompt lands in, has none to give. The prompt is the text the user
    typed, or "" for a prompt they didn't type, such as a watch wake, a message another
    thread sent, or a line that can't be parsed. [] when it can't be read. When strict, a
    session id or T3 database it can't read raises instead, so a caller can tell "the user
    sent it" from "can't tell". The nth entry with a text T3 knows an agent sent pairs with
    the nth message with that text in T3's state database, so a copy the user sent after
    the agent's stays theirs. T3 keeps fewer copies of a repeated scheduled prompt than
    the transcript does. A command Claude Code runs itself, such as /compact, and its output
    are no prompt, so the prompt after them answers the reply before them. An exchange's agent is True only for a prompt whose text T3 says
    only other agents sent, so neither a copy whose sender pairing is in doubt, a typed
    message whose text reads as "", such as one starting "Caveat:", nor one that only
    looks like a wake is one."""
    out, seen, reply, command = [], {}, None, False
    try:
        found = SESSION_ID.search(pathlib.Path(path).stem)
        if strict and not found:
            raise ValueError(f"no session id in {path}")
        senders = t3_child.senders(found.group(0), strict) if found else {}
        with open(path) as transcript:
            for line in transcript:
                try:
                    entry = json.loads(line)
                except (ValueError, RecursionError):  # Python 3.9 recurses on deep nesting
                    entry = None  # a line it can't parse counts as a prompt the user didn't type
                text = prompt_text(entry)
                if text is None:
                    said = reply_text(entry)
                    reply, command = (said, False) if said else (reply, command)
                    continue
                sent = "\n".join(texts(text_parts(entry))).strip()
                if note := SENDER_NOTE.match(sent):
                    sent = sent[note.end():]
                # A command Claude Code ran itself, such as /compact: the next prompt answers the reply before it.
                if command and sent.startswith("<local-command-stdout>"):
                    reply, command = out.pop().reply, False
                    continue
                command = sent.startswith("<command-name>")
                sent_by_agent = bool(senders) and bool(sent) and agent_sent(senders, seen, sent)
                # Only a text the user never sent is surely another agent's, however T3's copies pair.
                out.append(Exchange(reply, "" if sent_by_agent else text,
                                    sent_by_agent and "user" not in senders[sent]))
                reply = None
    except (OSError, TypeError, UnicodeDecodeError, RecursionError):  # partway too, so an earlier go doesn't stand
        return []
    return out


# final_reply reads this much of a file's end at most, a block at a time. In 298 Claude
# Code transcripts the last end_turn sat at most 17 KB from the end; in 128 Codex
# rollouts a final answer, at most 33 KB.
TAIL_BLOCK, TAIL_LIMIT = 64 * 1024, 512 * 1024


def tail_lines(path):
    """The file's complete lines, newest first, from at most its last TAIL_LIMIT bytes."""
    with open(path, "rb") as transcript:
        size = position = transcript.seek(0, 2)
        cut = b""  # the start of the line the last block began inside
        while position > 0 and size - position < TAIL_LIMIT:
            start = max(0, position - TAIL_BLOCK)
            transcript.seek(start)
            lines = (transcript.read(position - start) + cut).split(b"\n")
            position = start
            cut = lines.pop(0) if start else b""
            yield from reversed(lines)


def final_reply(path):
    """The text of the final reply the session's last finished turn ended on, read from
    the file's tail: Claude Code's `end_turn` message, Codex's `final_answer`. None when
    a prompt is newer than any final reply (an interrupted turn), the final message has
    no text, or the file can't be read.

    Claude Code writes one entry per content part, each with the message's id and stop
    reason, so the reply joins that message's text parts; a message that only thought
    has none. Codex's commentary comes before its final answer, with phase "commentary".
    Neither writes the prompt that runs a UserPromptSubmit hook before the hook: Claude
    Code 2.1.326 logs it as a queue-operation, and Codex records it after its hooks
    (codex-rs/core/src/session/turn.rs). Only a prompt with typed text counts as newer,
    since Codex may write an AGENTS.md block after a final answer."""
    parts, message_id = [], None
    try:
        for line in tail_lines(path):
            try:
                entry = json.loads(line) if line.strip() else None
            except (ValueError, RecursionError):
                entry = None
            if not isinstance(entry, dict):
                continue
            message = entry.get("message")
            assistant = entry.get("type") == "assistant" and isinstance(message, dict)
            if message_id:  # gathering the parts of the final message, back to its first
                if assistant and message.get("id") != message_id or not assistant and prompt_text(entry) is not None:
                    break
                if assistant:
                    parts.append(reply_text(entry) or "")
                continue
            if assistant and message.get("stop_reason") == "end_turn" and not any(entry.get(flag) for flag in FLAGS):
                message_id = message.get("id") or object()
                parts.append(reply_text(entry) or "")
                continue
            payload = entry.get("payload")
            if entry.get("type") == "response_item" and isinstance(payload, dict) \
                    and payload.get("phase") == "final_answer":
                return reply_text(entry)
            if prompt_text(entry):
                return None
    except (OSError, UnicodeDecodeError):
        return None
    text = "\n".join(part for part in reversed(parts) if part)
    return text if text.strip() else None

def prompts(path, strict=False):
    """Each prompt in the transcript at path, oldest first, as exchanges() reads it."""
    return [exchange.prompt for exchange in exchanges(path, strict)]


def user_messages(path):
    """Every typed user message in the transcript at path; [] when it can't be read."""
    return [text for text in prompts(path) if text]

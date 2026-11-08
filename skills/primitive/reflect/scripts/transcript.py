#!/usr/bin/env python3
"""Find and digest a Claude Code or Codex session transcript for reflect.

  transcript.py find [--cwd DIR]   newest sessions for DIR: path, modified, opening prompt
  transcript.py digest PATH        the whole session as Markdown, numbered by user turn
  transcript.py skills PATH        skills the session loaded or authored, with real paths
  transcript.py scan (--pattern RE | --hook SCRIPT [--prefilter RE]) [--cwd-glob GLOB] [--days N]
                                   count tool commands across every session that match

The digest keeps every message the user typed and each turn's final reply in full, and shortens
tool calls and intermediate text, so corrections in the middle of a long session
survive. Each tool line carries its JSONL line number (`L123`, or `p2:L123` in the second
file of a Codex session the user rewound) for the full record.
Python 3.9+, stdlib only.
"""
import argparse
import collections
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# The kit's reader of what the user typed, hooks/transcripts.py, linked in beside this file.
sys.path.append(str(Path(__file__).parent))
import transcripts  # noqa: E402

ASSISTANT_LIMIT = 1500
TOOL_LIMIT = 240
# Messages the harness injects as user turns. Unknown tags stay user turns, and so do
# the user's own input in tags: slash commands (<command-name>), Codex voice input
# (<realtime_delegation>), and answers to questions (<send_user_message_question_reply>).
INJECTED = re.compile(
    r"^\s*(<(system-reminder|task-notification|environment_context|app-context|user_instructions"
    r"|local-command-stdout|local-command-caveat|turn_aborted|external_[a-z_]+"
    r"|recommended_plugins|skill|in-app-browser-context|subagent_notification|heartbeat"
    r"|codex_delegation)[\s>]"
    r"|# AGENTS\.md instructions)")
# The Codex app puts the typed request under this header, sometimes inside an injected
# block such as <in-app-browser-context>.
REQUEST = re.compile(r"(?m)^## My request(?: for Codex)?:[ \t]*\n?")
SKILL_PATH = re.compile(r"(?:~|/)[^\s\"'`$;|&<>()]*/SKILL\.md")
NATIVE_SKILL = re.compile(r"^\s*<skill>\s*<name>[^<]*</name>\s*<path>([^<]+/SKILL\.md)</path>")
# Relative reads such as `cat build/SKILL.md` resolve against their command's workdir.
COMMAND_START = re.compile(r"(?=\bexec_command\s*\()")
RELATIVE_SKILL = re.compile(r"(?<![\w/.~-])((?:\.{1,2}/)?[\w.-]+(?:/[\w.-]+)*/SKILL\.md)")
WORKDIR = re.compile(r"workdir\\?[\"']?\s*:\s*\\?[\"']([^\"'\\]+)")
# A shell redirect or tee into a SKILL.md writes it rather than reading it.
SHELL_WRITE = re.compile(r"(?:>>?|\btee\s+(?:-a\s+)?)\s*\\?[\"']?([^\s\"'`$;|&<>()\\]*/SKILL\.md)")
PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update) File: (\S+/SKILL\.md)")
# Codex usually runs apply_patch inside an `exec` call, so strip patch bodies before
# looking for reads, whatever the outer tool is named.
PATCH_SPAN = re.compile(r"\*\*\* Begin Patch.*?(?:\*\*\* End Patch|$)", re.S)
BASE_DIRECTORY = "Base directory for this skill: "
CLAUDE_WRITES = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def shorten(text, limit):
    text = " ".join(str(text).split()) if limit <= TOOL_LIMIT else str(text).strip()
    return text if len(text) <= limit else text[:limit] + f" …[{len(text) - limit} more chars]"


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block_text(b.get("text") or b.get("content") or "") if isinstance(b, dict)
                         else block_text(b) for b in content)
    return ""


def records(path, stop=None):
    """Each JSON line with its line number, ending before byte offset `stop` if given."""
    offset = 0
    with open(path, "rb") as f:
        for number, raw in enumerate(f, 1):
            if stop is not None and offset >= stop:
                return
            offset += len(raw)
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


def session_files(path):
    """When the user edits an earlier message, Codex continues the session in a new
    rollout file named after the same id (rollout-<time>-<id>_<page>.jsonl). Return the
    files oldest first, each with the byte offset where the next file cut it: the kept
    history is every file up to its cut, and the rest of it is the abandoned branch."""
    path = Path(path).absolute()  # the sibling lookup walks up from the day folder
    sid = codex_session_id(path) if is_codex(path) else None
    files = [path]
    if sid and len(path.parents) >= 4:
        files = sorted(path.parents[3].glob(f"*/*/*/rollout-*{sid}*.jsonl"), key=lambda f: f.name)
        files = [f for f in files if codex_session_id(f) == sid] or [path]
    cuts = [(session_meta(after).get("history_base") or {}).get("end_byte_offset") for after in files[1:]]
    # A file with no history_base restarted the session, so nothing before it was kept.
    restarts = [i + 1 for i, cut in enumerate(cuts) if cut is None]
    start = restarts[-1] if restarts else 0
    return list(zip(files, cuts + [None]))[start:]


def codex_events(path):
    files = session_files(path)
    for page, (file, cut) in enumerate(files, 1):
        prefix = f"p{page}:" if len(files) > 1 else ""
        yield from codex_file_events(file, prefix, cut)
        if cut is not None:
            # Point at the last line kept before the cut, which can be session_meta alone.
            with open(file, "rb") as f:
                kept_lines = f.read(cut).count(b"\n")
            yield f"{prefix}L{max(kept_lines, 1)}", "rewound", "the user edited an earlier message here"


def codex_file_events(path, prefix, stop=None):
    for number, r in records(path, stop):
        line = f"{prefix}L{number}"
        p = r.get("payload") or {}
        if r.get("type") != "response_item":
            continue
        kind = p.get("type")
        if kind == "message" and p.get("role") in ("user", "assistant"):
            # Codex packs harness blocks and the user's text into one message: emit each
            # injected block on its own, and the rest of the message as one event.
            injected, rest = [], []
            for text in (block_text([block]) for block in p.get("content") or []):
                if p["role"] == "user" and is_injected(text):
                    header = REQUEST.search(text)
                    injected.append(text[:header.start()] if header else text)
                    if header:
                        rest.append(text[header.end():])
                elif text.strip():
                    rest.append(text)
            yield from ((line, "user", text) for text in injected)
            if rest:
                yield line, p["role"], "\n".join(rest)
        elif kind in ("function_call", "custom_tool_call"):
            yield line, "tool", (p.get("name"), p.get("arguments") or p.get("input") or "")
        elif kind in ("function_call_output", "custom_tool_call_output"):
            yield line, "result", block_text(p.get("output"))


def is_codex(path):
    with open(path, errors="replace") as f:
        first = f.readline()
    return '"session_meta"' in first or Path(path).name.startswith("rollout-")


def events(path):
    return codex_events(path) if is_codex(path) else claude_events(path)


def is_injected(text):
    return bool(INJECTED.match(text))


# An attachment the user sent with no text, unlike the interrupt marker transcripts.py also
# strips; a chip, such as a thread or PR the user attached, is transcripts.MARKER.
ATTACHED = re.compile(r"\[(?:Attached image|Image|Terminal|User attached)")


def own_words(text, senders, seen):
    """What the user typed in a message INJECTED passes, "" for one they didn't:
    transcripts.py drops what another agent sent and T3's notices and wakes, and reads a
    quote or slash command as the user's words. A message in a tag it doesn't know stays
    the user's, as INJECTED keeps it, and so does one that only attaches files."""
    if transcripts.agent_sent(senders, seen, text.strip()):
        return ""
    # T3's own context blocks hold no typed words once typed() reads their comments.
    rest = transcripts.APPENDED.sub("", text)
    kept = rest.lstrip().startswith("<") or ATTACHED.search(rest) or transcripts.MARKER.search(rest)
    return transcripts.typed(text) or (text.strip() if kept else "")


def digest(path):
    out, turn, replies = [f"# Session digest: {path}", ""], 0, []
    # A Codex rollout's name can end in a page suffix, so its id comes from session_meta.
    session = transcripts.SESSION_ID.search((codex_session_id(path) if is_codex(path) else Path(path).stem) or "")
    senders, seen = transcripts.t3_child.senders(session.group(0)) if session else {}, {}
    files = session_files(path) if is_codex(path) else [(Path(path), None)]
    if len(files) > 1:
        out[1:1] = [""] + [f"- p{page}: {file}" for page, (file, _) in enumerate(files, 1)]

    def flush_replies(turn_ends):
        # The last assistant text before the next user turn is the reply the user saw.
        for i, text in enumerate(replies):
            final = turn_ends and i == len(replies) - 1
            out.extend(["### reply" if final else "### assistant", "",
                        text.strip() if final else shorten(text, ASSISTANT_LIMIT), ""])
        replies.clear()

    for line, role, payload in events(path):
        if role == "tool":
            name, args = payload
            args = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            flush_replies(turn_ends=False)
            out.append(f"- tool {name} [{line}]: {shorten(args, TOOL_LIMIT)}")
            continue
        if not payload.strip():
            continue
        if role in ("user", "meta"):
            words = own_words(payload, senders, seen) if role == "user" and not is_injected(payload) else None
            if words is not None:  # a notice or wake starts a run of its own, after the reply
                flush_replies(turn_ends=True)
            if not words:
                out.append(f"- injected context [{line}]: {shorten(payload, TOOL_LIMIT)}")
                continue
            turn += 1
            out += ["", f"## Turn {turn} · user", "", words, ""]
            # The code, diff, or quote the words are about; a slash command's tags add nothing.
            if words != payload.strip() and not payload.lstrip().startswith("<command-"):
                out += [f"- with context [{line}]: {shorten(payload, ASSISTANT_LIMIT)}", ""]
        elif role == "assistant":
            replies.append(payload)
        elif role == "rewound":
            # The reply before a rewind is the one the user saw, then edited away from.
            flush_replies(turn_ends=True)
            out.append(f"- rewound after [{line}]: {payload}; the rest of that file was dropped")
        else:
            mark = "❌ " if role == "error" else ""
            out.append(f"  → {mark}{shorten(payload, TOOL_LIMIT)}")
    flush_replies(turn_ends=True)
    return "\n".join(out) + "\n"


def opening_prompt(path):
    for _, role, payload in events(path):
        if role == "user" and payload.strip() and not is_injected(payload):
            # The Codex app puts mentioned files and comments above the typed request.
            return shorten(REQUEST.split(payload, 1)[-1], 120)
    return "(no user message)"


def is_subagent(path):
    for _, r in records(path):
        source = (r.get("payload") or {}).get("source")
        return isinstance(source, dict) and "subagent" in source
    return False


def session_cwd(path):
    for _, r in records(path):
        cwd = r.get("cwd") or (r.get("payload") or {}).get("cwd")
        if cwd:
            return cwd
    return None


def editable(path):
    """Inside a git working tree, unless git ignores it, or the repo's skills-lock.json
    lists it: then it's a project-level `npx skills` install, which the next update
    overwrites."""
    result = subprocess.run(["git", "-C", str(Path(path).parent), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return False
    top, skill_dir = Path(os.path.realpath(result.stdout.strip())), Path(os.path.realpath(path)).parent
    # An ignored file can't be committed, such as a personal skill excluded from a team repo.
    ignored = subprocess.run(["git", "-C", str(skill_dir), "check-ignore", "-q", str(skill_dir / "SKILL.md")])
    if ignored.returncode == 0:
        return False
    # `npx skills` installs into these folders; a same-named skill elsewhere is source.
    if skill_dir.parent not in (top / ".agents" / "skills", top / ".claude" / "skills"):
        return True
    try:
        locked = json.loads((top / "skills-lock.json").read_text()).get("skills", {})
    except (OSError, ValueError):
        return True
    return skill_dir.name not in locked


def skills(path):
    """Loaded: the harness injected the skill's body, through Claude Code's "Base
    directory" row after a Skill call or a native $skill message in Codex. Read: a Codex
    shell command names the SKILL.md, a hint that it may have been read. A Claude Code
    Read is not a load, since every Edit needs one. Authored: written or patched this
    session, so it's under review rather than a guide the session followed; it drops
    any read hint for the same file."""
    cwd, codex = session_cwd(path) or os.getcwd(), is_codex(path)
    found, called = {}, set()

    def add(path_text, how):
        real = Path(os.path.expanduser(path_text))
        if real.exists():
            found.setdefault(Path(os.path.realpath(real)), set()).add(how)

    for _, role, payload in events(path):
        if role == "meta" and payload.startswith(BASE_DIRECTORY):
            add(os.path.join(payload[len(BASE_DIRECTORY):].split("\n")[0].strip(), "SKILL.md"), "loaded")
            continue
        if role == "user" and codex:
            # Codex loads a $skill by injecting its body as a <skill> message.
            native = NATIVE_SKILL.match(payload)
            if native:
                add(native.group(1), "loaded")
            continue
        if role != "tool":
            continue
        name, args = payload
        text = args if isinstance(args, str) else json.dumps(args)
        if name == "Skill" and isinstance(args, dict) and args.get("skill"):
            called.add(args["skill"].rsplit(":", 1)[-1])  # "plugin:skill" loads as "skill"
        elif name in CLAUDE_WRITES and isinstance(args, dict) and args.get("file_path", "").endswith("/SKILL.md"):
            add(args["file_path"], "authored")
        elif codex:
            for patched in PATCH_FILE.findall(text):
                add(patched if patched.startswith(("/", "~")) else os.path.join(cwd, patched), "authored")
            text = PATCH_SPAN.sub("", text)
            # A batched call holds several commands, each with its own workdir: resolve
            # each command's relative paths against its own, or the session's directory.
            for command in COMMAND_START.split(text):
                base = (WORKDIR.findall(command) or [cwd])[0]
                written = set(SHELL_WRITE.findall(command))
                mentioned = set(SKILL_PATH.findall(command)) | set(RELATIVE_SKILL.findall(command))
                for path_text, how in [(w, "authored") for w in written] + [(m, "read") for m in mentioned]:
                    add(path_text if path_text.startswith(("/", "~")) else os.path.join(base, path_text), how)
    for real, hows in sorted(found.items(), key=lambda item: item[0].parent.name):
        how = "+".join(sorted(hows - {"read"} if "authored" in hows else hows))
        print(f"{real.parent.name}\t{real}\t{'editable' if editable(real) else 'installed copy'}\t{how}")
    # A Skill call with no injected body: a built-in or a skill whose files moved.
    loaded_names = {real.parent.name for real, hows in found.items() if "loaded" in hows}
    for skill in sorted(called - loaded_names):
        print(f"{skill}\t(not found)\tunknown\tloaded")
    return 0


def find(cwd):
    cwd = os.path.realpath(cwd)
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    project = claude_home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", cwd)
    candidates = list(project.glob("*.jsonl"))
    # Every rollout, not the newest by name: a resumed session keeps its old start date.
    # Subagents share the parent's directory and opening prompt, so leave them out.
    rollouts = [p for p in (codex_home / "sessions").glob("*/*/*/rollout-*.jsonl")
                if os.path.realpath(session_cwd(p) or "") == cwd and not is_subagent(p)]
    # One row per Codex session: its first file (digest reads the rest) and newest time.
    sessions = {}
    for p in sorted(rollouts, key=lambda f: f.name):
        sessions.setdefault(codex_session_id(p) or p, []).append(p)
    rows = [(p, p.stat().st_mtime) for p in candidates]
    rows += [(session_files(files[-1])[0][0], max(f.stat().st_mtime for f in files)) for files in sessions.values()]
    rows.sort(key=lambda row: row[1], reverse=True)
    for p, mtime in rows[:5]:
        modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        print(f"{p}\t{modified}\t{opening_prompt(p)}")
    if not rows:
        print(f"no Claude Code or Codex sessions found for {cwd}", file=sys.stderr)
        return 1
    return 0


def all_sessions(days=None, cwd_glob=None):
    """Every top-level session: Claude Code project logs, and one entry per Codex session
    (its first rollout file; events() follows the rest). Subagents are left out."""
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    cutoff = datetime.now().timestamp() - days * 86400 if days else 0
    paths = list((claude_home / "projects").glob("*/*.jsonl"))
    first_files = {}
    for rollout in sorted((codex_home / "sessions").glob("*/*/*/rollout-*.jsonl"), key=lambda f: f.name):
        if not is_subagent(rollout):
            first_files.setdefault(codex_session_id(rollout) or rollout, rollout)
    paths += first_files.values()
    for path in paths:
        if path.stat().st_mtime < cutoff:
            continue
        if cwd_glob and not fnmatch.fnmatch(session_cwd(path) or "", cwd_glob):
            continue
        yield path


JS_CMD = re.compile(r"\bcmd\s*:\s*(['\"`])((?:\\.|(?!\1).)*)\1", re.S)
SHELL_TOOLS = {"Bash", "exec_command", "shell", "local_shell", "container.exec"}
JS_ESCAPE = re.compile(r"\\(?:x([0-9a-fA-F]{2})|u([0-9a-fA-F]{4})|u\{([0-9a-fA-F]{1,6})\}|(\r\n|[\s\S]))")
JS_CHARACTER = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
                "\n": "", "\r": "", "\r\n": "", "\u2028": "", "\u2029": ""}


def js_string(body):
    """A double-quoted JavaScript string's value, by JavaScript's escapes: "\\x70" and
    "\\u{70}" are "p", a backslash before a line break continues the line, and any other
    escaped character, such as the "d" in "\\d", is itself."""
    def character(match):
        code = match.group(1) or match.group(2) or match.group(3)
        if code:
            return chr(min(int(code, 16), 0x10FFFF))
        return JS_CHARACTER.get(match.group(4), match.group(4))
    # Join each \\uD83D\\uDE80 surrogate pair into the one character JavaScript reads.
    return JS_ESCAPE.sub(character, body).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def shell_command(name, args):
    """The shell command a tool call ran, or None when the call isn't a shell call, so
    Edit/Write payloads and patches that only mention a command never count. Reads Claude
    Code's `command`, Codex's `cmd` or `command` (a `["bash", "-lc", script]` array runs
    its script), and the `cmd` strings inside a Codex `exec` call's JavaScript."""
    if name == "exec" and isinstance(args, str) and "exec_command" in args:
        commands = [js_string(body) if quote == '"' else body for quote, body in JS_CMD.findall(args)]
        return "\n".join(commands) or None
    if name not in SHELL_TOOLS:
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return args
    if not isinstance(args, dict):
        return str(args)
    value = args.get("command") or args.get("cmd") or ""
    if isinstance(value, list):
        return value[-1] if len(value) >= 3 and value[-2] in ("-c", "-lc") else " ".join(value)
    return str(value)


def scan(pattern=None, hook=None, days=None, cwd_glob=None, prefilter=None):
    """Counts tool commands that match a regex, or that a PreToolUse hook would deny when
    run in the session's directory. Uses the same parser as digest, so injected text,
    subagents, and rewound branches are handled. A hook starts once per command, so pass
    its trigger words as `prefilter` to skip the rest."""
    regex = re.compile(pattern) if pattern else None
    gate = re.compile(prefilter) if prefilter else None
    scanned, hits = 0, collections.Counter()
    for path in all_sessions(days, cwd_glob):
        scanned += 1
        cwd = session_cwd(path) or os.getcwd()
        for _, role, payload in events(path):
            command = shell_command(*payload) if role == "tool" else None
            if command is None or (gate and not gate.search(command)):
                continue
            if regex:
                matched = bool(regex.search(command))
            else:
                request = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
                result = subprocess.run([hook], input=request, capture_output=True, text=True)
                matched = '"deny"' in result.stdout
            if matched:
                hits[str(path)] += 1
    print(f"{sum(hits.values())} matching commands in {len(hits)} of {scanned} sessions")
    for path, count in hits.most_common(10):
        print(f"{count:5}  {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("find").add_argument("--cwd", default=os.getcwd())
    sub.add_parser("digest").add_argument("path")
    sub.add_parser("skills").add_argument("path")
    scan_parser = sub.add_parser("scan")
    what = scan_parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--pattern")
    what.add_argument("--hook")
    scan_parser.add_argument("--prefilter")
    scan_parser.add_argument("--cwd-glob")
    scan_parser.add_argument("--days", type=int)
    args = parser.parse_args()
    if args.command == "find":
        return find(args.cwd)
    if args.command == "skills":
        return skills(args.path)
    if args.command == "scan":
        return scan(args.pattern, args.hook, args.days, args.cwd_glob, args.prefilter)
    sys.stdout.write(digest(args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

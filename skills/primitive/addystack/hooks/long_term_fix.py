#!/usr/bin/env python3
"""Stop: in a bug or alert session, send a reply back once with the user's own question
when it recommends or ships a code or config fix: is this the best long-term fix, or does
it just treat the symptom?

In 16 of 45 threads to Nov 10, 2026 where the user asked that, the agent's next reply
changed its own pick to the cause fix, usually within a minute and with no new research:
the better fix was in reach, and the agent never compared the two before it picked
option `a`. Five were Slack #error-monitoring alerts. A presence check for a stated cause
was ruled out, since the agents named the cause and still picked the patch, and so was
rewording the principle: on a replay eval of five of those picks, option `a` was the
cause fix in 2 of 5 on both the old and the new text (decision D-r57: a tie means no
change). So this asks the question itself, once, before the reply reaches the user.

A bug session is one that loaded diagnosing-bugs, got bug-route.py's context, or opened
on a Slack #error-monitoring thread, whose alerts don't load the skill. It lasts through
the workflow skills that turn goes on to load, as the Bug route plans and builds the fix,
and ends when one loads in a later turn. A reply asks when
its turn block's option `a` changes code or config (fix_option), or when its turn edited
files in the session's checkout and the user's message didn't pick the option that asked
for it, since that pick came from a reply this hook already saw. It passes when the
turn's message isn't one the user typed (a PR watch wake, a task notification, a T3
notice), when that message already asks the question, when an earlier bug-work reply's
option `a` had the same text, which the hook asked about then, and for T3 delegated
children, whose parent reads them. A message another agent sent still asks, since the
Slack bridge sends the alert threads' briefs; skipping them lost 12 of the 18 Linux-machine
fires on the replay. stop_hook_active keeps it to one send per
stop. Claude Code continues through additionalContext and Codex through decision: block,
as in routine_stop.py.

Replayed over the 60 days to Nov 10, 2026, on both machines' Claude Code and Codex
transcripts, it fires 28 times in 22 sessions: 18 in 14 on the Linux machine, where the
alert threads run, and 10 in 8 on the Mac. In four alert threads it fires on the reply the
user then asked that about, and in a fifth on the reply that built the fix they asked
about. Three fires are false, by a
read of each: two feature replies late in a session that had loaded diagnosing-bugs, and
one that offered to "reproduce, fix" before it knew the fix. Two are production hotfixes,
where the quick fix should stay. Only 213 of the 625 final replies in bug work carried a
turn block, so older replies are undercounted. Known limits:
- fix_option reads the option's first words, so these pass: a fix phrased with a verb it
  doesn't list, a fix after a step such as "run the test, then add a guard", and one that
  names Linear or a cycle. A doc-only "add the notes" asks.
- A message that only mentions "long-term" or "root cause" passes as if it asked.
- An edit counts by its tool call: a shell write doesn't count, and a failed edit does.
- A Codex tool call that only mentions a skill's SKILL.md, such as a search, reads as a
  load in routine_stop.loaded_skills, so it can start or end bug work.
- stop_hook_active is shared by every Stop hook, so when another sends the reply back
  first, this one passes on the resent reply."""
import importlib, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, routine_stop, transcripts, turn_block  # noqa: E402

bug_route = importlib.import_module("bug-route")

QUESTION = ("Before this reaches the user, their question: is this the best long-term fix, or does it just "
            "treat the symptom? Answer it, then send the reply again, with your pick changed if the answer "
            "changes it. A quick fix stays the pick when the cause fix is unrelated, large, or outside the "
            "change's scope, and the user didn't ask for it (fix-the-cause-in-scope). T3 shows only a turn's "
            "last message, so "
            "the resent reply has to stand on its own.")
# The user's own wording of the question, from the replies it flipped: when their message
# already asks it, the reply is the answer.
ASKED = re.compile(r"long[- ]term|best (?:[\w-]+ ){0,2}(?:fix|solution)|root cause|symptom|idiomatic|fix the cause"
                   r"|small patches|best practice", re.I)
# The brief a Slack #error-monitoring alert opens its thread with.
ALERT = re.compile(r"\A\s*Look into this Slack thread from #error-monitoring\b")
# bug-route.py's context, as Claude Code records it on the prompt it fired on.
ROUTED = "take the router's Bug route"
# An option that changes code or config: its first verb, after a "yes:" or "no:", is one
# of these, or it names a fix. A step that only ships, reviews, or reports one isn't.
CHANGE = re.compile(r"(?:add|adopt|allow|apply|bump|cap|catch|change|configure|convert|deny|disable|drop|enable"
                    r"|exclude|extract|filter|fix|gate|guard|handle|harden|ignore|implement|increase|limit|load"
                    r"|lower|make|move|patch|pin|raise|refactor|regroup|remove|rename|replace|restore|retry"
                    r"|return|revert|rewrite|scope|set|skip|split|suppress|switch|tag|throttle|treat|tune"
                    r"|update|upgrade|use|validate|wrap)(?:s|es|ed|ing)?\b", re.I)
NAMES_FIX = re.compile(r"(?<![\w/-])(?:fix|hotfix|patch)(?:es)?\b(?![/-])", re.I)
# A ticket step, such as "add DEV-3347 to the current cycle".
TICKET = re.compile(r"\b(?:the (?:current |next )?cycle|backlog|linear)\b", re.I)
NOT_CHANGE = re.compile(r"(?:wrap\s+up|archive|ask|babysit|check|close|create|deploy|diagnose|dig|draft|file|investigate|keep|leave"
                        r"|list|look|mark|merge|monitor|open|post|push|read|release|reply|rerun|re-run|review"
                        r"|run|send|stop\s+here|tell|verify|wait|watch)(?:s|es|ed|ing)?\b", re.I)
PREFIX = re.compile(r"\A\s*(?:(?:yes|no|go)\s*[:,—-]\s*)?(?:then\s+|now\s+|also\s+|first\s+)?", re.I)
# Claude Code's file tools, and Codex's patch tool.
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
# The files a Codex patch touches. Inside an exec call's code, its newlines are escaped.
PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: ([^\n\\]+)")
# A merge ships a change the hook already saw built, so stop:merge never asks.
FIX_CLASSES = {"routine", "decision", "stop:push", "stop:prod", "stop:post", "stop:credential"}


def fix_option(option):
    """True when option changes code or config."""
    if option is None or option.cls not in FIX_CLASSES:
        return False
    text = option.text[PREFIX.match(option.text).end():]
    if NOT_CHANGE.match(text) or TICKET.search(text):
        return False
    return bool(CHANGE.match(text) or NAMES_FIX.search(text))


def edited(entry, root):
    """True when entry is a tool call that edits a file under root: a Claude Code file
    tool, or a Codex patch, called directly or from an exec call's code."""
    if entry.get("type") == "assistant":
        content = (entry.get("message") or {}).get("content")
        calls = [(part.get("name"), (part.get("input") or {}).get("file_path") or (part.get("input") or {}).get("notebook_path"))
                 for part in content if isinstance(part, dict) and part.get("type") == "tool_use"] \
            if isinstance(content, list) else []
    elif entry.get("type") == "response_item":
        payload = entry.get("payload") or {}
        if payload.get("type") not in ("function_call", "custom_tool_call"):
            return False
        name, code = payload.get("name"), str(payload.get("input") or payload.get("arguments") or "")
        if name == "exec" and "tools.apply_patch(" in code:
            name = "apply_patch"
        calls = [(name, path.strip()) for path in PATCH_FILE.findall(code)] if name == "apply_patch" else []
        calls = calls or [(name, None)]
    else:
        return False
    for name, path in calls:
        if name not in EDITS:
            continue
        if path is None or not root:
            return True
        if os.path.normpath(os.path.join(root, path)).startswith(os.path.normpath(root) + os.sep):
            return True
    return False


class Session:
    """What the hook reads from a transcript in one pass."""

    def __init__(self, path):
        self.bug = False  # diagnosing-bugs loaded, bug-route fired, or an alert thread
        self.prompt = None  # the latest prompt's typed text, "" when the user didn't type it
        self.earlier = set()  # option `a` texts of earlier replies in bug work
        self.edited = False  # this turn edited a file in the session's checkout
        root, first, reply, started = None, True, None, False
        try:
            with open(path, errors="ignore") as transcript:
                for line in transcript:
                    try:
                        entry = json.loads(line)
                    except (ValueError, RecursionError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    root = root or entry.get("cwd") or (entry.get("payload") or {}).get("cwd")
                    text = transcripts.prompt_text(entry)
                    if text is not None:  # close the turn before the prompt's own skill load counts
                        if self.bug and self.prompt and not bug_route.NOTICE.match(self.prompt):
                            self.earlier.add(recommended(reply))  # a reply the hook could have asked about
                        started = False
                        if first and ALERT.match("\n".join(transcripts.texts(transcripts.text_parts(entry) or []))):
                            self.bug = started = True
                        first = first and not text  # an injected AGENTS.md entry isn't the user's first message
                        self.prompt, self.edited, reply = text, False, None
                    self.bug = self.marks_bug(entry, self.bug, started)
                    started = started or self.starts_bug(entry)
                    if text is None:
                        reply = transcripts.reply_text(entry) or reply
                        self.edited = self.edited or edited(entry, root)
        except (OSError, TypeError):
            pass
        self.earlier.discard(None)

    @staticmethod
    def starts_bug(entry):
        """True when entry starts bug work: diagnosing-bugs loads, or bug-route's context."""
        if "diagnosing-bugs" in routine_stop.loaded_skills(entry):
            return True
        content = (entry.get("message") or {}).get("content") if entry.get("isMeta") is True else None
        first = content if isinstance(content, str) else next(
            (part.get("text", "") for part in content or [] if isinstance(part, dict)), "") \
            if isinstance(content, list) else ""
        if isinstance(first, str) and bug_route.LOADED.match(first):
            return True
        attachment = entry.get("attachment") if entry.get("type") == "attachment" else None
        return isinstance(attachment, dict) and attachment.get("hookEvent") == "UserPromptSubmit" \
            and ROUTED in json.dumps(attachment.get("content"))

    @staticmethod
    def marks_bug(entry, bug, started=False):
        """Whether the session is in bug work after entry. starts_bug starts it, and another
        workflow skill loading ends it, unless bug work started in the same turn (started):
        the router's Bug route goes on to plan and autopilot in that turn."""
        if Session.starts_bug(entry):
            return True
        if routine_stop.loaded_skills(entry):
            return bug and started
        return bug


def recommended(reply):
    """The text of reply's option `a`, or None."""
    try:
        option = turn_block.parse(reply).recommended if reply else None
    except turn_block.Malformed:
        return None
    return option.text if option else None


def ask(event):
    """Why this stop goes back, or None."""
    if event.get("stop_hook_active") or bare_references.delegated_child(event):
        return None
    try:
        turn = turn_block.parse(event.get("last_assistant_message"))
    except turn_block.Malformed:
        return None  # routine_stop.py sends it back
    if turn.state == "running":
        return None
    session = Session(event.get("transcript_path"))
    prompt = session.prompt
    if not session.bug or not prompt or bug_route.NOTICE.match(prompt) or ASKED.search(prompt):
        return None
    option = turn.recommended
    if fix_option(option) and option.text not in session.earlier:
        return QUESTION
    if session.edited and not routine_stop.PICK.match(prompt):
        return QUESTION
    return None


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if isinstance(event, dict) and (feedback := ask(event)):
        routine_stop.send(event, feedback)


if __name__ == "__main__":
    main()

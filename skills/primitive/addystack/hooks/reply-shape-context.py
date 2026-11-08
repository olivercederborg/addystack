#!/usr/bin/env python3
"""SessionStart: load the user's reply rules into their own sessions, on every source,
including resumes and forks. Subagents don't run SessionStart hooks, so they skip it.
Replaces the import in ~/.claude/CLAUDE.md, which subagents load too: 568 of 990
subagent transcripts in the month to Oct 15, 2026 carried it. Codex runs it too, as its
SessionStart hook from ~/.codex/hooks.json.

Two manifest entries run it, each gated by the reply preferences in resolved.json, so a
user who turned one off gets nothing from it:

    reply-shape-context.py          reply-shape's SKILL.md, when replies.style is reply-shape
    reply-shape-context.py --rules  the file replies.rules names, when one is set

They stay two payloads because past 10,000 characters Claude Code injects only a
2,000-character preview, and reply-shape plus a rules file can pass that together.
REPLY_SHAPE_SKILL overrides reply-shape's path. A reply-shape that can't load warns; a
rules file that can't load outputs nothing, since `addystack doctor` reports it.

T3 delegated child tasks do run SessionStart, yet only their parent reads their reports,
so they skip it too, unless a line of their brief starts with "Reply rules: on". The
check finds the session's thread in T3's state database (T3_STATE_DB overrides its
path), and a missing, locked, or changed database loads the rules as before. Known
limit: the user chatting directly in a delegated child's thread gets no rules."""
import json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child  # noqa: E402

LIMIT = 10_000


def skips_rules(session_id):
    """True for a T3 delegated child whose brief doesn't opt in. Any doubt reads as False."""
    brief = t3_child.delegated_brief(session_id)
    return brief is not None and not t3_child.rules_on(brief)


def skill_path():
    """Where reply-shape's SKILL.md loads from."""
    return pathlib.Path(os.environ.get("REPLY_SHAPE_SKILL",
                                       "~/.claude/skills/reply-shape/SKILL.md")).expanduser()


def context(path):
    """The additionalContext that loads path, without its frontmatter. Raises OSError."""
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return f"These are the user's reply rules, from {path}. Follow them on every reply.\n\n" + text.lstrip()


def output(name, path):
    """The hook's output for one rules file, warning when it's over the hook limit."""
    loaded = context(path)
    result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": loaded}}
    if len(loaded) > LIMIT:
        result["systemMessage"] = (f"⚠️ {name} is over the hook limit ({len(loaded):,} of {LIMIT:,} "
                                   "characters), so it loads as a 2,000-character preview.")
    return result


def chosen(rules_mode):
    """The (name, path) this entry loads under the user's reply preferences, or None."""
    import resolved
    replies = resolved.replies()
    if rules_mode:
        return (replies.rules.name, replies.rules) if replies.rules else None
    return ("reply-shape", skill_path()) if replies.style == "reply-shape" else None


def main(argv):
    # Settings rendered before the --rules flag pass the rules file's path instead. Read
    # any argument as rules mode, so those entries keep loading the rules, not
    # reply-shape twice, until the hooks are rendered again.
    rules_mode = len(argv) > 1
    picked = chosen(rules_mode)
    if picked is None:
        return
    # Every source loads the rules, so only the session id is read.
    try:
        session_id = json.loads(sys.stdin.read()).get("session_id")
    except (ValueError, AttributeError):
        session_id = None
    if skips_rules(session_id):
        return
    name, path = picked
    try:
        print(json.dumps(output(name, path)))
    except OSError as error:
        if rules_mode:
            return
        warning = f"⚠️ {name} couldn't load from {path} ({error.strerror}), so replies use the default format."
        print(json.dumps({"systemMessage": warning, "hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": warning}}))


if __name__ == "__main__":
    main(sys.argv)

#!/usr/bin/env python3
"""UserPromptSubmit: when the user's message reports a failure (failing, crashed, broken, a
regression) and the session hasn't loaded diagnosing-bugs, point the agent at the router's
Bug route.

In the 60 days to Nov 2, 2026, 20 of the 23 work-repo sessions with a typed failure report
never loaded diagnosing-bugs. In one Expo upgrade session, five reports ("deployments to
the production app are failing", "failed to build on EAS", "the app crashed") got fixes
shipped before their cause was confirmed, though the route sits in router.md, which loads
every turn. Replayed over those 60 days, the hook fires 44 times in 25 sessions. Some
are questions or mentions, which the conditional context leaves to the agent.
Only text the user typed counts (transcripts.typed): watch wakes, harness messages, messages
another thread sent, and T3 delegated children pass."""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, t3_child, transcripts  # noqa: E402

FAILURE = re.compile(r"\b(?:fail(?:s|ed|ing|ures?)?|crash(?:es|ed|ing)?|broken|regress(?:ed|ions?)|throw(?:s|ing)?)\b", re.I)
# T3 notices that read as typed text.
NOTICE = re.compile(r"\s*(?:T3 Code stopped watching|You generate concise git branch names)")
LOADED = re.compile(r"Base directory for this skill: [^\n]*/diagnosing-bugs\b")
CONTEXT = ("The user's message mentions a failure. When it reports one and asks you to fix or look "
           "into it, take the router's Bug route unless an earlier route matches (a coordinator "
           "thread, a repeated correction): load diagnosing-bugs when it's installed, then plan, "
           "then autopilot. A question about why something failed gets an answer.")


def loaded(transcript_path):
    """True when Claude Code injected the skill: a meta entry that opens with its banner. A
    message or tool output that quotes the banner doesn't count."""
    try:
        with open(transcript_path, errors="ignore") as transcript:
            for line in transcript:
                if "diagnosing-bugs" not in line:
                    continue
                entry = json.loads(line)
                if not isinstance(entry, dict) or entry.get("isMeta") is not True:
                    continue
                content = (entry.get("message") or {}).get("content")
                first = content if isinstance(content, str) else next(
                    (part.get("text", "") for part in content or [] if isinstance(part, dict)), "")
                if isinstance(first, str) and LOADED.match(first):
                    return True
    except (OSError, TypeError, ValueError):
        pass
    return False


def agent_sent(session_id, prompt):
    creators = t3_child.senders(session_id).get(prompt.strip())
    return bool(creators) and creators[-1] == "agent"


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        return
    # T3 appends earlier turns as "[Historical …]" blocks after the text the user typed.
    text = transcripts.typed(prompt).split("[Historical ", 1)[0]
    if not text or NOTICE.match(text) or not FAILURE.search(text):
        return
    if loaded(event.get("transcript_path")) or agent_sent(event.get("session_id"), prompt) \
            or bare_references.delegated_child(event):
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": CONTEXT}}))


if __name__ == "__main__":
    main()

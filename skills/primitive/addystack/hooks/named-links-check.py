#!/usr/bin/env python3
"""PreToolUse, in Claude Code and Codex: before a PR body or comment, or a Linear issue,
comment, or project, goes out (posted_text.py), denies it once when its text cites an issue
or PR id without a link whose text names it (named_links.py), listing the ids. The agent
looks up the titles and posts again; an identical retry passes (denied_posts.py), so an id
it can't name never holds it. A reminder, not a guardrail: any error or doubt passes."""
import json, pathlib, sys
from typing import List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def reason(flagged: List[Tuple["posted_text.Post", List["named_links.Cited"]]]) -> str:
    """The denial: each target's unnamed ids, asking for `[ID, title](url)`, and to keep
    GitHub's `Closes #12` as written and name the id once elsewhere."""
    raise NotImplementedError


def main() -> None:
    import denied_posts, named_links, posted_text
    event = json.load(sys.stdin)
    found = posted_text.posts(event.get("tool_name"), event.get("tool_input"), event.get("cwd"))
    flagged = [(post, cited) for post in found for cited in [named_links.unnamed(post.text)] if cited]
    fresh = [(post, cited) for post, cited in flagged
             if denied_posts.first(event.get("session_id"), post.target, post.text)]
    if fresh:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason(fresh)}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass

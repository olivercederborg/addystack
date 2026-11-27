#!/usr/bin/env python3
"""UserPromptSubmit, in Claude Code and Codex: when the reply the user last saw cites an
issue or PR id without a link whose text names it (named_links.py), adds context only
the agent sees, asking it to cite each as `[ID, title](url)` from now on. It never
blocks the prompt and never asks for the old reply again, so no second reply posts; a
Stop hook that sent replies back did (commit 08be571).

It reads the reply from the transcript's tail (transcripts.final_reply), so a prompt
after a clean reply costs a few milliseconds and opens neither T3's database nor
resolved.json; only a reply with an unnamed id asks t3_child whether this session is a
delegated child, which skips it as it skips the reply rules. Any error or doubt outputs
nothing. Known limits: it corrects replies from the next message on, never the one
already shown, and a reply no message follows gets no notice."""
import json, pathlib, sys
from typing import List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def notice(ids: List[str]) -> str:
    """The context that names ids and asks for named links from now on."""
    listed = ", ".join(ids)
    return (f"Your last reply cited {listed} without a link whose text names it. From now on, "
            "cite each issue or PR as `[ID, title](url)` the first time a reply mentions it, "
            "such as `[DEV-3127, Allow failure-only export emails](https://linear.app/…)`, "
            "looking the title up rather than guessing it. Don't repost or rewrite the earlier "
            "reply, and don't bring these ids into an answer they're unrelated to. Keep a turn "
            "block's option text, such as `merge #124` or `push #N (dismisses X's approval)`, "
            "as written, since the merge and push gates read it, and each Next line that shows "
            "a push option word for word, since push-gate matches a typed go against it: name "
            "the id once elsewhere in the reply, such as its headline or table, which covers "
            "the bare id in that line.")


def main() -> None:
    try:
        event = json.loads(sys.stdin.read())
        import transcripts
        reply = transcripts.final_reply(event["transcript_path"])
        if not reply:
            return
        import named_links
        found = named_links.unnamed(reply)
        if not found:
            return
        import t3_child
        if t3_child.skips_rules(event.get("session_id")):
            return
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": notice([cited.id for cited in found])}}))
    except Exception:  # a hook that can't tell outputs nothing, never blocks the prompt
        return


if __name__ == "__main__":
    main()

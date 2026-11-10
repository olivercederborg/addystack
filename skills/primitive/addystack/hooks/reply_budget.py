#!/usr/bin/env python3
"""Stop: send a reply back once when a merge option's text isn't the plain request that
merge-gate.py takes as the user's go.

reply-shape's rules are taste, set by what the reader needs at that moment, and this hook
checks only the reply's machine contracts. A merge option the user picks with a bare
letter counts as a go only when its text is a literal merge request (merge_go.py), so
"merge #90 once its webhook test passes, then deploy" costs them a typed go. In the 60
days to Nov 10, 2026, 27 of 347 merge options in delivered T3 replies weren't plain, in
13 threads, and the user picked 11 of them with a bare letter. An option of class
`stop:merge` that only marks PRs ready, with no merge in its text, passes. The turn
block's own validity is routine_stop.py's send-back.

It used to send replies back for length and layout: more than 100 words of headline and
notes, a fact table past five rows, a label off its list, or a value past 25 words, Risk
rows below others, a Pick with no Source, and scope-grill's 60-word round, Size trail,
and Assuming line. Replayed over the same 60 days of delivered replies, paired with the
user's next typed message, none showed a catch: 4,674 replies past 100 words drew a
"what is X?" ask as often as the rest (2.2% each), the 26 "too long" complaints followed
one in 38% of cases against 46% of all replies, 2 of 118 "is this idiomatic?" asks
followed an unsourced Pick, and the fact table rules and scope-grill checks fired on 0
to 9 delivered replies with no ask after any; the Assuming line's 3 were the Oct 31
round it was built from. Meanwhile they sent drafts back about 1,320 times in 60 days.
The user's call on Nov 10, 2026: primitives composed per context, not word or row
counts.

Claude Code continues through additionalContext and Codex through decision: block, as
in bare_references.py, and stop_hook_active keeps it to one send per stop. T3 delegated
children pass, since their parent reads them, unless their brief has a "Reply rules: on"
line."""
import json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bare_references, merge_go, t3_child, turn_block  # noqa: E402

MERGES = re.compile(r"\bmerge", re.I)


def unplain(reply):
    """The reply's merge options whose text merge_go doesn't read as a literal go."""
    try:
        options = turn_block.parse(reply).options
    except turn_block.Malformed:
        return []  # routine_stop.py sends a reply without a valid block back
    return [option for option in options
            if option.cls == "stop:merge" and MERGES.search(option.text) and not merge_go.literal_go(option.text)]


def feedback(options):
    listing = "\n".join(f"- `{option.key}` → {option.text}" for option in options)
    return ("These merge options aren't the plain request merge-gate takes as the user's go, so a pick "
            "of one wouldn't let the merge through:\n" + listing + "\nWrite each as the merge alone, such "
            "as \"merge #12 and #13\", and put any step before or after it in the reply or in another "
            "option. Send your whole reply again with the same change in Next and in the turn block. "
            "T3 shows only a turn's last message, so the resent reply has to stand on its own. Add no "
            "note about the change.")


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active"):
        return
    if bare_references.delegated_child(event) and not t3_child.rules_on(bare_references.first_brief(event)):
        return
    found = unplain(event.get("last_assistant_message") or "")
    if not found:
        return
    if "turn_id" in event:
        print(json.dumps({"decision": "block", "reason": feedback(found)}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback(found)}}))


if __name__ == "__main__":
    main()

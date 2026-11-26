#!/usr/bin/env python3
"""Stop, in Claude Code: sends a reply back once when its turn block (turn_block.py) offers a
`stop:push` or `stop:merge` option the gate would refuse as the user's go, so the agent
rewords it before the user picks it. A refused pick costs the user a pick, a denial, and a
new card: on Nov 26, 2026 push-gate refused three informed goes in a row on one push
(PushGate in test_hooks.py replays them).

It checks only what the reply can know offline:
- a `stop:merge` option that mentions merging must be merge_go.literal_go, as merge-gate.py
  reads a pick: "merge #12 and #13", not "merge #12, #13, and #14" or "merge only #12". A
  ready-only option, such as "mark #12 ready", passes;
- a `stop:push` option that mentions dismissing must be push_go.literal_go, as push-gate.py
  reads a pick. Whether a push dismisses an approval depends on reviews the reply can't
  see, so an option that names no dismissal passes, and so does one whose PRs the gate
  would find incomplete.

Of 1,198 cards with such a class from Nov 18 to 26, 2026, on two machines, 27 options were
ones it flags. T3 shows a reply as it streams, so the user sees the first card too; the
resent one comes seconds later and is the one a key answers (user_turn.answered).
stop_hook_active keeps it to one send per stop, and any doubt or error passes."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DISMISS = re.compile(r"\bdismiss", re.I)
MERGE = re.compile(r"\bmerg", re.I)


def refused(turn):
    """(option, the go it should be) for each option of turn the gate would refuse."""
    import merge_go, push_go
    found = []
    for option in turn.options:
        if option.cls == "stop:merge" and MERGE.search(option.text) and not merge_go.literal_go(option.text):
            found.append((option, 'the plain merge request and nothing else, as in "merge #12 and #13", which merge-gate '
                                  "takes as the user's go"))
        elif option.cls == "stop:push" and DISMISS.search(option.text) and not push_go.literal_go(option.text):
            found.append((option, "the push first, naming each PR, then the dismissal, as in \"push #12 and #13 "
                                  "(dismisses the reviewer's approval)\" or \"push the stack (dismisses the reviewer's "
                                  "approvals on #12 and #13)\", then only steps such as \"post the reply\", with no other "
                                  "step before the push and no condition, delay, or question, which push-gate takes as "
                                  "the user's go"))
    return found


def main():
    try:
        event = json.loads(sys.stdin.read())
        if event.get("stop_hook_active"):
            return
        import turn_block
        found = refused(turn_block.parse(event.get("last_assistant_message") or ""))
    except Exception:  # Malformed included: no block, nothing to check
        return
    if found:
        reason = "; ".join(f'option {option.key}, "{option.text}", is {option.cls}, but the gate would refuse it if the '
                           f"user picked it: write it as {shape}" for option, shape in found)
        # Claude Code continues a Stop through additionalContext, shown as "Stop hook feedback";
        # its docs keep "block" for errors.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
            f"{reason}. Send your whole reply again with only that option reworded, or split into its own step. "
            "T3 shows the turn's last message as its reply, so the resent reply has to stand on its own. "
            "Add no note about the change.")}}))


main()

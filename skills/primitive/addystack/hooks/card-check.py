#!/usr/bin/env python3
"""Stop, in Claude Code: sends a reply back once when its turn block (turn_block.py) offers a
`stop:push` option that asks for a push (a push_go.STEPS verb) and says it dismisses an
approval, but isn't a go push-gate.py takes (push_go.literal_go), so the agent rewords it
before the user picks it.
A refused pick costs the user a pick, a denial, and a new card: on Nov 26, 2026 push-gate
refused three informed goes in a row on one push (PushGate in test_hooks.py replays them).

It checks only what the reply can know offline. Whether a push dismisses an approval
depends on reviews the reply can't see, so an option that names no dismissal passes, and so
does one whose PRs the gate would find incomplete. An option holding a refusal or a
condition (push_go.REFUSAL), such as "don't push #12, it dismisses the approval", asks for
no push, so it passes. A `stop:merge` option isn't checked: merge-gate reads the go only
for a PR with no checks, which the reply can't see either.

Of 1,198 cards with a push or merge stop from Nov 18 to 26, 2026, on two machines, it flags
20 push options, 15 distinct. T3 shows a reply as it streams, so the user sees the first card too;
the resent one comes seconds later and is the one a key answers (user_turn.answered).
stop_hook_active keeps it to one send per stop, and any doubt or error passes."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DISMISS = re.compile(r"\bdismiss", re.I)
SHAPE = ("the push first, naming each PR, then the dismissal, as in \"push #12 and #13 (dismisses the reviewer's "
         "approval)\" or \"push the stack (dismisses the reviewer's approvals on #12 and #13)\", then only steps such as "
         "\"post the reply\", with no other step before the push and no delay, which push-gate takes as the user's go")


def refused(turn):
    """Each option of turn that asks for a push dismissing an approval that push-gate wouldn't take."""
    import push_go
    return [option for option in turn.options if option.cls == "stop:push" and DISMISS.search(option.text)
            and push_go.STEPS.search(option.text) and not push_go.REFUSAL.search(option.text)
            and not push_go.literal_go(option.text)]


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
        reason = "; ".join(f'option {option.key}, "{option.text}", is stop:push, but push-gate would refuse it if the '
                           f"user picked it" for option in found)
        # Claude Code continues a Stop through additionalContext, shown as "Stop hook feedback";
        # its docs keep "block" for errors.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
            f"{reason}. Write it as {SHAPE}. Send your whole reply again with only that option reworded, or its "
            "other steps split into their own option. T3 shows the turn's last message as its reply, so the resent "
            "reply has to stand on its own. Add no note about the change.")}}))


main()

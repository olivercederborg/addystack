#!/usr/bin/env python3
"""Stop: send the agent on when its turn ends on a routine step, and send a reply back
once when it has no valid turn block.

The router lists the stops, yet agents kept ending turns on steps outside them: the user
answered a bare "a" 1,287 times in the 14 days to Oct 21, 2026. Telling those steps from
stops by the reply's English took a dozen regexes and still guessed, so each final reply
now ends with a turn block (rules_file(): the Turn block section of the user's reply rules
file, or the kit's references/turn-block.md), and this reads it: when the state is
stop, nothing needs the user, and the recommended option's class is routine, the agent does
that option instead of asking, whatever the block's `standing` list holds: those items, still
open from earlier replies, don't block the step. It stays out of the way when the turn
answers their question or a read-only request such as "show me …", since the router ends
those with options, and after "no autonomy". A reply
whose block is missing or malformed goes back once with the reason, since this hook and
merge-gate.py read nothing without it.

A reply with more than two options goes to the reply log (reply_log.py). Of 1,922 replies
in three weeks that offered a `b`, the user picked it 59 times, and 6 of 538 `c`s; they
steered in their own words instead (docs/research/2026-10-28-reply-audit.md). So the turn
block allows `a`, and `b` only when the reply stops for their call. It's a format rule, so
it's logged rather than sent back, which would post the card twice (suite-audit R153).
A reply sent on to do `a` isn't logged, since it doesn't stop on its options.
turn_block.py still reads three, so a reply with a third keeps its picks for merge-gate.py.

Claude Code continues through additionalContext and Codex through decision: block, as
in bare_references.py. stop_hook_active keeps each to one send per stop; the log still takes
that stop's reply, since a row can't loop. T3 delegated
children pass, since their parent reads them, except a coordinator's worker: its reply goes
back once unless its block's `project` is its brief's `Project:` name, which Prefrontal
groups its threads by.

In a teammate review, the user files issues themselves unless they ask for one. Of the 80
Claude Code sessions on a Linux machine that ran review-teammate-pr by Nov 2, 2026, 9 offered
to file a Linear issue, in 26 options, one through to creating it, and none after the user
asked for one; issue_step() matches those 26 and none of the 574 other options. On #4912 this
hook then sent the agent on to draft one, since it was a routine option. So a reply in
such a session whose options draft, file, or create an issue goes back once, before the
routine check, unless the user's latest message asks for one, in their words or by picking an
option that offers one. The review lasts until another workflow skill loads.
Known limits: a Codex session counts as a review when it reads review-teammate-pr's
SKILL.md, editing it included. issue_step() reads words, not intent: "I'll create the
issue myself" reads as an ask, though no message of the user's has said so, and an offer
that names no issue ("I create it") or turns things "into issues" passes."""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, reply_log, resolved, t3_child, transcripts, turn_block  # noqa: E402

NEXT_MAX = 2  # the turn block's options; a reply with more is logged
# A step that writes an issue: "draft a Linear issue", "file 1 as a Linear follow-up",
# "create this issue in Linear", "draft a Trigger.dev GitHub issue". issue_step() rejects
# "the open issue", "a test for the (Linear) issue", a verb negated in its own clause, and
# words in quotes or parentheses, such as a pasted PR title.
STEP = re.compile(r"\b(file|create|open|draft|write|raise|log|make)((?:\s+[^\s;!?]+){0,6}?)\s+(issues?|tickets?|linear)\b",
                  re.I)
ASIDE = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|\([^)\n]*\)')
NEGATED = re.compile(r"\b(?:not|never|no|don'?t|without)\s+(?:(?!and\b|then\b)[^\s,;.]+\s+){0,4}$", re.I)
DETERMINER = re.compile(r"\b(?:the|a|an|this|that|its|their|any)\s+$", re.I)
# A pick that may carry a tweak: "b", "a, but change the title", "a and then start a thread".
# Looser than turn_block.picked(), which merge-gate.py needs exact.
PICK = re.compile(r"\s*`?([a-d])`?(?=\s*$|\s*[,.:;!]|\s+(?:and|but|then|with|plus)\b)", re.I)
PREPOSITIONS = {"about", "after", "against", "at", "by", "for", "from", "in", "into", "of", "on", "to", "under", "with"}
REVIEW_SKILL = "review-teammate-pr"
# The router's workflow skills: the review is over once one of these loads after it.
WORKFLOWS = {REVIEW_SKILL, "address-review", "architect", "autopilot", "babysit", "build", "coordinator", "correct",
             "diagnosing-bugs", "open-pr", "review-loop", "scope-grill", "tdd", "verify-work"}
# A question, or a read-only request the router answers the same way, in one clause: "show
# me the project file". A bare verb ("show reply images inline", "list the PRs in the README")
# asks for a change, and so does a request that goes on to one ("show me the error and fix
# it", "…; fix it"). Known limits, each sent on as before: "list the open PRs", "describe
# the fix", and "explain the gap between A and B".
QUESTION = re.compile(r"\?\s*$|^(?:what|why|how|is|are|does|can|should|which|when|where|who)\b"
                      r"|^(?:please\s+)?(?:show me|tell me|explain|walk me through)\b"
                      r"(?!.*(?:\b(?:and|then)\b|[;.!]\s*\S))", re.I | re.S)


def should_continue(turn, messages):
    """The routine option to just do, or None when the turn may end on its question."""
    option = turn.recommended
    # needs only: a standing item is open from an earlier reply and doesn't block this step.
    if turn.state != "stop" or turn.needs or not option or option.cls != "routine":
        return None
    if not messages or QUESTION.search(messages[-1]):
        return None
    if any("no autonomy" in message.lower() for message in messages):
        return None
    return option


def issue_step(text):
    """True when text drafts, files, or creates an issue."""
    text = ASIDE.sub(" ", text)
    for match in STEP.finditer(text):
        verb, between, noun = match.group(1).lower(), match.group(2).lower().split(), match.group(3).lower()
        before = text[:match.start()]
        # "log it in Linear" names where the issue goes; "a test for the Linear issue" names an existing one.
        stray = PREPOSITIONS.difference({"in", "into", "to"} if noun == "linear" else ()).intersection(between)
        if stray or verb == "open" and not between and DETERMINER.search(before) or NEGATED.search(before):
            continue
        return True
    return False


def loaded_skills(entry):
    """The workflow skills an entry loads, in order: a Claude Code Skill call or slash
    command, or a Codex tool call that names a skill's SKILL.md."""
    if not isinstance(entry, dict):
        return []
    message = entry.get("message") if entry.get("type") == "assistant" else None
    content = message.get("content") if isinstance(message, dict) else None
    found = [part["input"].get("skill") for part in content if isinstance(part, dict)
             and part.get("type") == "tool_use" and part.get("name") == "Skill" and isinstance(part.get("input"), dict)] \
        if isinstance(content, list) else []
    if command := re.match(r"/([\w-]+)", transcripts.prompt_text(entry) or ""):
        found.append(command.group(1))
    payload = entry.get("payload") if entry.get("type") == "response_item" else None
    if isinstance(payload, dict) and payload.get("type") in ("function_call", "custom_tool_call"):
        found += re.findall(r"([\w-]+)/SKILL\.md", json.dumps(payload))
    return [name for name in found if name in WORKFLOWS]


def teammate_review(path):
    """True when review-teammate-pr is the last workflow skill the session loaded."""
    last = None
    try:
        with open(path) as transcript:
            for line in transcript:
                if any(name in line for name in WORKFLOWS):
                    try:
                        last = (loaded_skills(json.loads(line)) or [last])[-1]
                    except ValueError:
                        continue
    except (OSError, TypeError, UnicodeDecodeError):
        return False
    return last == REVIEW_SKILL


def asked_for_issue(path):
    """True when the user's latest message asks for an issue, in their words or by picking an
    option that offers one."""
    for exchange in reversed(transcripts.exchanges(path)):
        if exchange.prompt:
            return issue_step(exchange.prompt) or issue_step(picked_text(exchange.reply, exchange.prompt))
    return False


def picked_text(reply, prompt):
    """The text of the option prompt picks from reply's turn block, "" when it picks none."""
    key = PICK.match(prompt)
    try:
        options = turn_block.parse(reply).options if key and reply else ()
    except turn_block.Malformed:
        return ""
    return next((option.text for option in options if option.key == key.group(1).lower()), "")


def issue_offer(turn, path):
    """The option that drafts, files, or creates an issue in a teammate review, or None
    when there's none, the user's latest message asked for one, or the session isn't a
    teammate review."""
    option = next((option for option in turn.options if issue_step(option.text)), None)
    if not option or asked_for_issue(path) or not teammate_review(path):
        return None
    return option


def project_feedback(reply, project):
    """Why a worker's reply goes back, or None when its block's project is its brief's, or
    when no block can hold that name, such as one past 40 characters."""
    # JSON's escapes keep a "<" or ">" in the name from opening a block or closing the comment.
    done = "<!-- turn " + json.dumps({"state": "done", "needs": [], "options": [], "project": project},
                                     ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e") + " -->"
    try:
        turn_block.parse(done)
    except turn_block.Malformed:
        return None
    try:
        named = turn_block.parse(reply).project
    except turn_block.Malformed as error:
        problem = f"Your reply has no valid turn block: {error}."
    else:
        if named == project:
            return None
        problem = (f"Your reply's turn block names project {json.dumps(named)}." if named
                   else "Your reply's turn block has no `project`.")
    return (f"{problem} Your brief's `Project:` line names {json.dumps(project, ensure_ascii=False)}, and a "
            "coordinator worker's final reply ends with a turn block whose `project` is that name. "
            "Send your whole reply again, unchanged except that it ends with that block as its only one, such as "
            f"{done} for a finished report ({rules_file()}, Turn block section). Add no note about the change.")


def rules_file():
    """The user's reply rules file when it has a Turn block section, else the kit's own
    spec, references/turn-block.md, as ~/… under $HOME, so a send-back never cites a section
    that isn't there."""
    path = resolved.replies().rules
    try:
        if not (path and re.search(r"(?m)^ {0,3}#{1,6}[ \t]+Turn block(?:[ \t]+#+)?[ \t]*$", Path(path).read_text())):
            path = None
    except (OSError, UnicodeDecodeError):
        path = None
    # Beside this hook, not the kit state records, which can name an older checkout.
    path = path or Path(__file__).resolve().parent.parent / "references" / "turn-block.md"
    try:
        return "~/" + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


def send(event, feedback):
    if "turn_id" in event:
        print(json.dumps({"decision": "block", "reason": feedback}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    active = event.get("stop_hook_active")
    if bare_references.delegated_child(event):
        project = t3_child.worker_project(bare_references.first_brief(event))
        feedback = not active and project and project_feedback(event.get("last_assistant_message"), project)
        if feedback:
            send(event, feedback)
        return
    try:
        turn = turn_block.parse(event.get("last_assistant_message"))
    except turn_block.Malformed as error:
        if not active:
            send(event, f"Your reply has no valid turn block: {error}. Send your whole reply again, "
                 f"unchanged except that its last line is a valid turn block ({rules_file()}, Turn block section). "
                 "T3 shows only a turn's last message, so the resent reply has to stand on its own. "
                 "Add no note about the change.")
        return
    offer = None if active else issue_offer(turn, event.get("transcript_path"))
    option = None if active or offer else should_continue(turn, transcripts.user_messages(event.get("transcript_path")))
    # A reply sent on to do `a` doesn't stop on its options; any other shows them.
    if not option and len(turn.options) > NEXT_MAX:
        reply_log.record(event, "routine_stop", [("options-cap", f"{len(turn.options)} options, over {NEXT_MAX}")])
    if offer:
        send(event, f"\"{offer.text}\" offers an issue in a teammate review, and the user files those themselves "
             "unless they ask for one. Put the problem in a note for them instead, with no option to draft, "
             "file, or create an issue, and no PR comment unless they pick one. Send your whole reply again "
             "with that option gone, in Next and in the turn block. T3 shows only a turn's last message, so "
             "the resent reply has to stand on its own. Add no note about the change.")
    elif option:
        send(event, f"\"{option.text}\" isn't a stop: nothing needs the user, and the router gives every "
             "step outside its Stops and the plan's gates autonomy (router.md, Plan and "
             "Continuation). Do it now. T3 shows only a turn's last "
             "message and folds the rest away, so your final reply has to stand on its own: "
             "carry forward what the reply above told the user, with the step's result added.")


if __name__ == "__main__":
    main()

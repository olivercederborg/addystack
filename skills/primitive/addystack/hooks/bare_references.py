#!/usr/bin/env python3
"""Stop: send a reply back when its Next, Needs you, or Done lines cite a number without
saying what it is, as in "keep item 48 as it is" or "fix 21–33".

The user acts on those lines without scrolling up, and the numbers often come from places
they never saw: an orchestrator's brief ("item 48", "rule 21"), a fold, or a turn before a
compaction. On Oct 21, 2026 the user had to ask "what is 'item 48'?"; before this hook, 332 of
4,088 final replies in the 14 days before, across 85 sessions, had such a line.

A number is named when a parenthetical with words follows it, "48 (optional email
variables)", when a comma and a name follow it, "milestone 2, Update saved workout", or
when it sits in a parenthetical after words, "the orchestrator's go (rule 21)". In a list,
each number needs its own name, or one parenthetical names them all in order, "items 2
and 3 (undo delete, full-text search)". A number the same reply defines on a visible
line ("**1** · Blocker · …", "| 1 | …") is on screen already. PR numbers pass: they're
real names, and most are the thread's own PR. The turn block (turn_block.py) is a
comment, so it isn't read as text, but a number that is the id of one of its needs or
standing items gets that item's name in the feedback, so the fix is a copy.

Claude Code and Codex both pass the reply as `last_assistant_message`, and both
continue the turn with the feedback. T3 delegated children pass, since their parent
reads them. Known limit: a coined label ("the catch-all row") isn't
a number, so only the reply rules catch it. scripts/check_examples.py runs the same
check on the kit's example replies."""
import itertools, json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child, turn_block  # noqa: E402

FOLD = re.compile(r"<details>.*?</details>", re.S)
ZONE = re.compile(r"^\*\*(Next|Done|Needs you)\*\*")
# A reader item: a note that opens with its label, or a row of reply-shape's fact table.
LABEL = re.compile(r"^\s*(?:[-*] )?\*\*(Decide|Review|Do)\*\*|^\s*\|\s*(Decide|Review|Do)\s*\|")
NUMS = r"\d+(?!\.\d)(?:\s*(?:[–-]|,|and|or|to|&)\s*\d+)*"
KEYWORD = re.compile(
    r"\b(?:items?|rules?|findings?|rows?|milestones?|questions?|decisions?|lessons?|nits?|"
    r"cards?|layers?|options?|points?)\s+(" + NUMS + r")\b(?!\s+of\b)", re.I)
# What follows a count: "fix 3 bugs", "2 failing tests". "post 1 as a question" is a reference.
COUNT = r"\s*(?:%|(?!(?:as|is|was|has|its|this|plus|does)\b)[A-Za-z]+s\b|[A-Za-z]+\b\s*(?:files?|tests?|lines?))"
VERB = re.compile(
    r"\b(?:fix|fixes|skip|keep|drop|apply|discuss|address|answer|revert|ship|resolve|"
    r"close|reopen|split|pick|defer|reword|park|post|send)\s+(?:only\s+|also\s+|just\s+)?(" + NUMS +
    r")\b(?!" + COUNT + ")", re.I)
SUBJECT = re.compile(r"^\s*(?:[-*] )?(" + NUMS + r")\s+(?:is|are|stays?|remains?|needs?|still)\b")
UNIT = re.compile(r"\d+(?!\.\d)(?:\s*(?:[–-]|to)\s*\d+)?")
LIST_SEP = re.compile(r"\s*(?:,\s*(?:and|or|&)?|and|or|&)\s*(?=\d)")
IS_COUNT = re.compile(COUNT, re.I)
# Named right after the number: "(words)", or a comma and a name, "2, Update saved workout".
NAMED_AFTER = re.compile(r"(?:'s)?\s*(?:\((?=[^)]*[A-Za-z]{3})[^)]*\)|,\s+(?:the\s+|an?\s+)?[A-Z][a-z]|,\s+the\s)")
# A visible line that defines a number: "**1** · …", "1. …", "48: …", "| 1 | …", "### Option 1 · …".
DEFINES = re.compile(r"^\s*(?:[-*]\s+)?(?:#+\s*)?(?:[A-Z][a-z]+\s+)?(\d+)\s*(?:·|—|[.:)]\s|\||$)|^\|\s*(\d+)\s*\|")


def shown(text):
    """The reply's lines without its turn block and folds, and for each whether it sits in
    a code block."""
    text = turn_block.lines_ended(text)
    at = text.rfind("<!--")
    if at >= 0 and turn_block.BLOCK.match(text, at):
        text = text[:at]
    lines = FOLD.sub("", text).split("\n")
    return lines, turn_block.in_fence(lines)


def visible(text, blank_code=False):
    """The reply without its turn block, folds, and code blocks, which the reader doesn't
    see or scan. With blank_code, each code line becomes a blank line instead, so the
    blocks around a code block stay apart."""
    lines, fences = shown(text)
    if blank_code:
        return ["" if fenced else line for line, fenced in zip(lines, fences)]
    return [line for line, fenced in zip(lines, fences) if not fenced]


def plain(line):
    """Drops code spans, link targets, emphasis, and quotes, so they don't hide or fake a
    number. A quoted phrase ("start layer 3") is an example or a citation, not a reference."""
    line = re.sub(r"`[^`]*`", "code", line)
    line = re.sub(r"\"[^\"]*\"|“[^”]*”", "quote", line)
    line = re.sub(r"\]\([^)]*\)", "]", line)
    return re.sub(r"[*_]{1,2}", "", line)


def zone_lines(lines):
    """Next, Done, and Needs you lines, plus Decide, Review, and Do items anywhere, as a
    note or as a table row with that label."""
    zone = None
    for line in lines:
        head = ZONE.match(line)
        if head:
            zone = head.group(1)
        elif zone == "Needs you" and line.strip() and not line.lstrip().startswith(("-", "*")):
            zone = None
        if zone or LABEL.match(line):
            yield line


def inside_named_paren(line, start):
    """True when the number sits in a parenthetical that follows words: 'the go (rule 21)'."""
    open_at = line.rfind("(", 0, start)
    return open_at > 0 and line.find(")", open_at) >= start and re.search(r"[A-Za-z]{3}", line[:open_at])


def units(text, pos):
    """The cited list from pos, as (number or range, named) pairs. Each needs its own name,
    so "fix 1 and 2 (null dates)" leaves 1 bare, and "fix 1 (currency column) and 2"
    leaves 2 bare, unless the parenthetical holds one name per number: "fix 1 and 2
    (currency column, null dates)". A range such as "21–33" takes one name for the whole
    range, and a count after the first ends the list: "fix 48 (…) and 2 tests"."""
    out = []
    while (match := UNIT.match(text, pos)) and not (out and IS_COUNT.match(text, match.end())):
        pos = match.end()
        named = NAMED_AFTER.match(text, pos)
        out.append((match.group(0), bool(named)))
        if named:
            pos = named.end()
            group = list(itertools.takewhile(lambda unit: not unit[1], reversed(out[:-1])))
            names = re.split(r",|;|\band\b|&", named.group(0)) if "(" in named.group(0) else []
            if group and len([name for name in names if name.strip(" ()'s")]) == len(group) + 1:
                out[-1 - len(group):] = [(unit, True) for unit, _ in out[-1 - len(group):]]
        sep = LIST_SEP.match(text, pos)
        if not sep:
            break
        pos = sep.end()
    return out


def bare_numbers(line):
    text = plain(line)
    found = []
    for pattern in (KEYWORD, VERB, SUBJECT):
        for match in pattern.finditer(text):
            if inside_named_paren(text, match.start(1)):
                continue
            lead = text[match.start():match.start(1)].strip(" -*")
            found += [f"{lead} {unit}".strip() for unit, named in units(text, match.start(1)) if not named]
    return found


def defined(lines):
    """Numbers the reply itself defines on a visible line, so a reference to them is on screen."""
    return {m.group(1) or m.group(2) for line in lines if (m := DEFINES.match(plain(line)))}


def problems(text, names={}):
    """One line per bare number in the reply's Next, Needs you, and Done lines. A number
    that is an item's id in names, from the turn block, gets that item's name beside it:
    "'fix 3' (3 → currency column) in: …"."""
    lines = visible(text)
    known = defined(lines)
    found = []
    for line in zone_lines(lines):
        for ref in bare_numbers(line):
            numbers = dict.fromkeys(re.findall(r"\d+", ref))
            if set(numbers) <= known:
                continue
            hint = ", ".join(f"{number} → {names[int(number)]}" for number in numbers if int(number) in names)
            found.append(f"{ref!r}{f' ({hint})' if hint else ''} in: {line.strip()}")
    return found


def first_brief(event):
    """The session's opening brief: the T3 child's first message, or else the transcript's
    first user message, or None."""
    brief = t3_child.delegated_brief(event.get("session_id"))
    if brief is not None:
        return brief
    try:
        with open(event.get("transcript_path")) as transcript:
            for line in transcript:
                entry = json.loads(line)
                if entry.get("type") != "user":
                    continue
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                return content if isinstance(content, str) else None
    except (OSError, TypeError, ValueError, AttributeError):
        pass
    return None


def delegated_child(event):
    """True for a T3 delegated child. Its parent, not the user, reads its replies, and takes
    the last message as the result. T3's state database answers for Claude Code and Codex
    alike. Without it, a Claude transcript whose brief opens "Act as the <role> sub-agent"
    still counts."""
    if t3_child.delegated_brief(event.get("session_id")) is not None:
        return True
    try:
        with open(event.get("transcript_path")) as transcript:
            for line in transcript:
                entry = json.loads(line)
                if entry.get("type") != "user":
                    continue
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                first = content.lstrip().split("\n", 1)[0] if isinstance(content, str) else ""
                return first.startswith("Act as the ") and "sub-agent" in first
    except (OSError, TypeError, ValueError, AttributeError):
        pass
    return False


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active") or delegated_child(event):
        return
    reply = event.get("last_assistant_message") or ""
    try:
        names = {need.id: need.name for need in turn_block.parse(reply).items}
    except turn_block.Malformed:
        names = {}  # routine_stop.py sends a reply without a valid block back
    found = problems(reply, names)
    if not found:
        return
    listing = "\n".join(f"- {line}" for line in found)
    feedback = (
        "These lines cite a number without saying what it is, and the user acts on them "
        "without scrolling up:\n" + listing + "\nSend your whole reply again, unchanged except "
        "that each of these numbers gets its short name in parentheses after it, as in \"keep "
        "48 (optional email variables)\"; where a line shows \"3 → currency column\", that's "
        "the name your turn block gives item 3. T3 shows only a turn's last message and folds the "
        "rest away, so the resent reply has to stand on its own. Add no note about the "
        "change. A number from a brief, a standing rule, or before a compaction needs its "
        "name too: look it up rather than guess.")
    # Codex's Stop takes only decision and reason, and its input carries turn_id. Claude
    # Code's docs keep "block" for errors and continue through additionalContext, which
    # the transcript labels "Stop hook feedback" with no hook error notice.
    if "turn_id" in event:
        print(json.dumps({"decision": "block", "reason": feedback}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))

if __name__ == "__main__":
    main()

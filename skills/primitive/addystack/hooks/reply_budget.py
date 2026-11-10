#!/usr/bin/env python3
"""Stop: send a reply back when its glance runs long. Two numbers: reply-shape's writing
target keeps the headline and notes under 60 words, and this hook sends a reply back only
above 100. The user's call on Nov 5, 2026 (D-r60): in the 7 days before, the send-back fired
385 times across 103 of 2,163 Mac Claude transcripts; the drafts it caught held a median
of 93 words, and 61% held under 100. It also checks that a changed
scope-grill plan Size shows as a trail on its line, or in a diff, against the previous round. A scope-grill
round's **Assuming** line must name an assumed value, not only point at a report or its
"defaults": on Oct 31 three mobile-mica rounds said "audit's Q2–Q13 defaults (pending)",
and the user overturned one hidden value (biometrics inside `auth`) after three `a` picks. A scope-grill
round counts its glance as grill_words does: its plan items count, its code and diff blocks and
fixed labels don't, and it goes back at 60 words, scope-grill's own limit: prose
instructions alone let eval players run to 67 and 91 words on Oct 31 (decision D-R13-3).
The user freed the diff blocks on Nov 3: "A snippet- or diff-like code block should also not
count toward the 60-word limit". A plan fenced as a diff still counts, since its lines are
plan items.
A decision card whose recommended option is a decision also goes back when it has no
**Source** label above the closing and its **Pick** doesn't cite a URL, path:line, named
doc, or ADR or decision id itself. The user's pick on the Nov 7 weekly card: Nov 2–6, 238 of
287 Pick cards had no Source line, and 11 of their 19 "is this idiomatic?" asks came right
after one. Of that week's 215 Pick cards with a decision recommended, it sends back 146,
two of the weekly's three cases among them (D-r75a); the third, a plan review, has no
**Pick**. A ship gate, post, or push passes, since its view carries the checks. The note
joins any other send-back, so it's one per stop.
A merge option goes back too when its text isn't the plain request merge-gate takes as a go
(merge_go.literal_go), such as "merge #90, then deploy": a bare-letter pick of it costs the
user a typed go. In the 60 days to Nov 10, 2026, 27 of 347 merge options in delivered T3
replies weren't plain, in 13 threads, and the user picked 11 of them with a bare letter. An
option of class `stop:merge` that only marks PRs ready passes. Known limits: it reads merge
words, so "ready to merge" reads as a merge and "don't forget to merge" or "land #12" as none;
merge-gate.py still refuses any pick that isn't a literal go.
A delegated child whose brief has a "Reply rules: on" line plays the user's session, so it
is sent back like one.

The user runs many agents at once and gives each reply a glance. In the three weeks to Oct
28, 2026, the median final reply to a message they typed held 140 words of prose outside
code, folds, and Next, and they answered 38% of their messages with a bare letter
(docs/research/2026-10-28-reply-audit.md). Rules alone had already failed three times:
"keep it short, sweet and useful", "a wall of text in a format that i cant read at all".

The glance is what's left of the reply's visible lines (bare_references.visible: no turn
block, folds, or code blocks) above its closing, which starts at the last `---` line, or
at `**Next**` or `**Done**` without one. Drafts (`>` lines), images, and a Do item's
numbered steps don't count, since reply-shape exempts them, and neither does a table of
up to six body rows, which reply-shape counts as a view; a longer table counts. The one
line ending in ":" right before a code block or such a table counts with its view, unless
it's the headline, a list item or its wrapped line, or a heading: the user's D-r47-leadin,
after a lead-in sentence put view replies at 60 to 73 words. A step runs, as a CommonMark
list item does, through the lines indented at least to its text's column; any other
numbered line, and any paragraph after the steps, counts. A word is a token with a
letter or a digit, so `·`, `→`, and markers are free. Claude Code continues through
additionalContext and Codex through decision: block, as in bare_references.py, and
stop_hook_active keeps it to one send per stop. T3 delegated children pass, since their
parent reads them, unless their brief opts in with "Reply rules: on"; so does a session
where a message of the user's opens by asking for "normal replies".
A reply whose turn block says `running` passes, since reply-shape makes it one ⏳ line.
`scripts/check_examples.py` holds the kit's example replies to the 60-word target.

reply-shape's fact table, the two-column table right under the headline, is a short table,
so the word count skips it; it has its own limits instead, which fact_problems checks: at
most FACT_ROWS rows under the header, each label one of FACT_LABELS, each value within
FACT_SEND_BACK words (FACT_WORDS is the writing target, as 60 is to 100), and Risk and
Unsure rows first with ⚠️ leading the value, and no unescaped pipe in a value, since
Markdown ends the cell there and drops the rest. The limits come from the mockups the user
picked from, whose longest value ran 22 words, and from a trial on Nov 9, 2026: 36 replies
that fresh agents wrote under the rule, on Fable 5.2 and Opus 5.5, held 191 values with a
median of 15 words and none past 21. The user's call on Nov 9, 2026, after seeing
UI cards in use: every final reply is a headline, one fact table, and the closing. A fact
table isn't required: a session started before that keeps the old shape until it restarts.
So a table counts as one only when it has two columns, is the first thing under a headline
that opens with its marker (a round's strip may sit between), and at least one row's label is
on the list; fact_table reads that from the reply's own lines, after three review rounds each
found another way a filtered view of them took an older reply's table for one: in the 7 days before, 85 of
7,575 final replies had a two-column table under the headline, a PR list or a status list,
and one of them had a listed label, the first fact table written. Its Pick and Source rows
count for the source check, and numbered steps under a table with a Do row are that Do's
steps, as under a Do note. Known limits: a fact table whose every label is off the list
reads as a comparison view, as before, and so does one below a lead-in sentence or under a
headline without its marker.

reply-shape's items, a report's list of several things, are the same fact table in list
form: a top-level list item that opens with a bold name that isn't a fact label, then a
clause of at most ITEM_WORDS words. Up to TABLE_ROWS of them don't count when each clause
runs at most ITEM_SEND_BACK words; a longer item or list, and the details under an item,
count. Counting every item word sent back 13 of 45 eval replies written under the items
rule on Nov 10, 2026, against 4 of 45 under the fact table, while their visible words
matched (medians 108 and 113); with the clause rule, a 25-word clause exemption let the
wall of text that started this hook pass, and a 15-word one still sends it back at 108
words. Over 8,990 delivered T3 replies from the 60 days to Nov 10, it frees 164 of the
4,302 the count put over 100, and sends back none it passed."""
import json, pathlib, re, sys
from typing import NamedTuple, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bare_references, merge_go, t3_child, transcripts, turn_block  # noqa: E402

BUDGET = 60  # reply-shape's writing target, which check_examples holds examples to
SEND_BACK = 100  # the send-back limit: a glance above it goes back
CLOSING = re.compile(r"^\*\*(?:Next|Done)\*\*")
DRAFT = re.compile(r"^\s*(?:>|!\[)")
STEP = re.compile(r"^\s*\d+\.\s+")
DO = re.compile(r"\*\*Do\*\*")
# A GFM table: a header row and a delimiter row with the same number of cells, outer pipes
# optional, then body rows up to a blank line or the start of another block.
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
# An HTML block opens with a tag, a closing tag, a comment, or a declaration, not an autolink.
BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|>|#{1,6}\s|`{3,}|~{3,}|([-*_])(?:[ \t]*\1){2,}[ \t]*$"
                         r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>|$)|<!--|<\?|<![A-Z])")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
TABLE_ROWS = 6  # the most body rows a table can hold and still be a view
# An item: a top-level list line that opens with its name in bold, "- **Currency column**: …".
ITEM_LEAD = re.compile(r"^[-*+]\s+\*\*([^*\n]+?):?\*\*:?")
ITEM_WORDS = 12  # reply-shape's clause after an item's name
ITEM_SEND_BACK = 15  # an item whose clause runs past this counts, as FACT_SEND_BACK is to FACT_WORDS
# reply-shape's fact table: its labels, row cap, and words per value (target, send-back).
FACT_LABELS = ("Risk", "Unsure", "Why", "Effect", "Proof", "Undo", "Skipped", "Queued",
               "Pick", "Source", "Cost", "Decide", "Review", "Do")
WARNED = ("Risk", "Unsure")  # these rows come first, and ⚠️ leads their value
FACT_ROWS = 5
FACT_WORDS = 20
FACT_SEND_BACK = 25
# A round's strip, the one line that may sit between the headline and the fact table.
STRIP = re.compile(r"[\w ]*?\d+\s*[🟡⬜✅]\ufe0f?(?:\s*·\s*[\w ]*?\d+\s*[🟡⬜✅]\ufe0f?)+")  # Group 1 🟡 · 2 ⬜ · 3 ⬜
HEADLINE = re.compile(r"\s*[✅🟡🔴⏳]")  # reply-shape's headline opens with its marker
OPT_OUT = re.compile(r"^\W*(?:(?:use|back to|switch to|give me)\s+)?normal replies\b", re.I)
WORD = re.compile(r"\w", re.U)


def over(count):
    """True when a glance of count words breaks reply-shape's "under 60"."""
    return count >= BUDGET


def cells(line):
    """A table row's cells: split on pipes a backslash doesn't escape, after one outer pipe
    at each end. A backslash escapes the character after it, so the pipe in `\\\\|` splits."""
    row = line.strip()
    row = row[1:] if row.startswith("|") else row
    found, cell, escaped = [], "", False
    for char in row:
        if char == "|" and not escaped:
            found.append(cell)
            cell = ""
        else:
            cell += char
        escaped = char == "\\" and not escaped
    # The outer pipe at the end closes the last cell and opens none.
    return found if found and not cell and row.endswith("|") else [*found, cell]


def tables(lines):
    """Each Markdown table in lines, as (first line, line after the last, body rows). Known
    limit: a one-column table whose rule row has no pipe isn't found, so it counts."""
    n = 0
    while n < len(lines):
        header, rule = lines[n], lines[n + 1] if n + 1 < len(lines) else ""
        if ("|" in header and "|" in rule and TABLE_RULE.match(rule) and not BLOCK_START.match(header)
                and len(cells(header)) == len(cells(rule))):
            end = n + 2
            while end < len(lines) and lines[end].strip() and not BLOCK_START.match(lines[end]):
                end += 1
            yield n, end, end - n - 2
            n = end
        else:
            n += 1


def views(lines):
    """Indexes of the lines in Markdown tables of up to TABLE_ROWS body rows."""
    return {n for start, end, rows in tables(lines) if rows <= TABLE_ROWS for n in range(start, end)}


class Row(NamedTuple):
    at: int  # the row's line in the reply
    label: str
    value: str  # the cell Markdown draws
    cut: bool  # an unescaped pipe ends the value early, and Markdown drops the rest


class Fact(NamedTuple):
    header: str  # the header row's value
    rows: Tuple[Row, ...]
    broken: bool  # an unescaped pipe in the header's value, so Markdown draws no table


def fact_table(reply):
    """reply-shape's fact table, as a Fact, or None without one. It's read from the reply's
    own lines, since what a filtered view drops (a code block, a fold) would otherwise sit
    unseen between the headline and a table: the first line opens with the headline's
    marker, a round's strip may follow, and the next line that isn't blank is a two-column
    table's header, indented less than code, with a row whose label is on the list. Any
    other table is a view, as the module docstring says. A row's line number is the same in
    bare_references.shown's lines, as nothing above the table is dropped there."""
    lines = turn_block.lines_ended(reply).split("\n")
    text = [n for n, line in enumerate(lines) if line.strip()]
    if not text or not HEADLINE.match(lines[text[0]]):
        return None
    under = text[2:] if len(text) > 1 and STRIP.fullmatch(lines[text[1]].strip()) else text[1:]
    if not under or under[0] + 1 >= len(lines):
        return None
    start = under[0]
    header, rule = lines[start], lines[start + 1]
    if (len(header) - len(header.lstrip(" ")) > 3 or header[:1] == "\t" or "|" not in header or BLOCK_START.match(header)
            or "|" not in rule or not TABLE_RULE.match(rule) or len(cells(rule)) != 2 or len(cells(header)) < 2):
        return None
    end = start + 2
    while end < len(lines) and lines[end].strip() and not BLOCK_START.match(lines[end]):
        end += 1
    rows = tuple(Row(n, found[0].strip().strip("*").strip(), found[1].strip() if len(found) > 1 else "", len(found) > 2)
                 for n in range(start + 2, end) for found in [cells(lines[n])])
    if not any(listed(row.label) for row in rows):
        return None
    return Fact(cells(header)[1].strip(), rows, len(cells(header)) > 2)


def listed(label, among=FACT_LABELS):
    return label.casefold() in {name.casefold() for name in among}


def fact_problems(reply, limit=FACT_SEND_BACK):
    """What breaks the fact table's limits in a reply that has one, one clause each."""
    table = fact_table(reply)
    if not table:
        return []
    found = []
    # Markdown ends a cell at a pipe, in inline code too. A third header cell no longer
    # matches the rule row, so no table is drawn; a third cell in a row is dropped.
    if table.broken:
        found.append("its header value holds an unescaped |, so Markdown draws no table; write \\|")
    if len(table.rows) > FACT_ROWS:
        found.append(f"it has {len(table.rows)} rows under its header, over {FACT_ROWS}")
    for label in dict.fromkeys(row.label for row in table.rows if not listed(row.label)):
        found.append(f"\"{label}\" isn't one of its labels")
    for label in dict.fromkeys(row.label for row in table.rows if row.cut):
        found.append(f"its {label} value holds an unescaped |, which cuts the rest off; write \\|")
    for label, value in [("header", table.header), *((row.label, row.value) for row in table.rows)]:
        count = sum(1 for token in value.split() if WORD.search(token))
        if count > limit:
            found.append(f"its {label} value runs {count} words, over {FACT_WORDS}")
    warned = [listed(row.label, WARNED) for row in table.rows]
    if warned != sorted(warned, reverse=True):
        found.append("a Risk or Unsure row sits below another row")
    if any(not row.value.lstrip("*_ ").startswith("⚠") for row in table.rows if listed(row.label, WARNED)):
        found.append("a Risk or Unsure value doesn't start with ⚠️")
    return found


def fact_feedback(reply):
    """The send-back text for a fact table past its limits, or None."""
    found = fact_problems(reply)
    if not found:
        return None
    return (f"Your reply's fact table breaks reply-shape's limits: {'; '.join(found)}. The table under the "
            f"headline holds at most {FACT_ROWS} rows of `label | value` under its header, each label one of "
            f"{', '.join(FACT_LABELS)}, each value at most {FACT_WORDS} words, with Risk and Unsure rows first "
            "and ⚠️ leading their value. Send your whole reply again with the table inside those limits: "
            "merge rows that share a label, give a row no label fits to a view under the table, such as "
            "its own comparison table, and move the rest to the fold. T3 shows only a turn's last message, so "
            "the resent reply has to stand on its own. Add no note about the change.")


def lead_ins(lines, fenced, short):
    """Indexes of the lead-in lines: a paragraph line at the left margin that ends in ":"
    with only blank lines between it and a code block or a short table. The headline, a
    list item or its wrapped line, and a heading never lead in. reply-shape counts a
    lead-in with the view it introduces (decision D-r47-leadin)."""
    # last: the latest non-blank line, when it could lead in; headline: none seen yet.
    found, last, headline = set(), None, True
    for n, line in enumerate(lines):
        if fenced[n] or n in short:
            if last is not None:
                found.add(last)
            last, headline = None, False
        elif line.strip():
            text = line.rstrip()
            last = n if (not headline and text.endswith(":") and not text[:1].isspace()
                         and not ITEM.match(text) and not HEADING.match(text)) else None
            headline = False
    return found


def glance(reply):
    """The reply's headline and notes: its visible lines above the closing, without
    drafts, images, short tables and the lead-in line before a view, or the numbered steps
    under a Do note or a fact table's Do row."""
    raw, fenced = bare_references.shown(reply)
    lines = ["" if code else line for line, code in zip(raw, fenced)]
    cell = {n for start, end, _ in tables(lines) for n in range(start, end)}
    rules = [n for n, line in enumerate(lines) if line.strip() == "---" and n not in cell]
    end = rules[-1] if rules else next((n for n, line in enumerate(lines)
                                        if CLOSING.match(line.strip()) and n not in cell), len(lines))
    short = views(lines[:end])
    short |= lead_ins(lines[:end], fenced[:end], short)
    fact = fact_table(reply)
    do_rows = {row.at for row in fact.rows if listed(row.label, ("Do",))} if fact else set()
    kept, do, step = [], False, 0  # step: the open step's text column, 0 when none
    items, lead = [], 0  # lead: the open item's text column, 0 when none
    column = 0  # the open Do item's text column: a table left of it ends the item
    for n, line in enumerate(lines[:end]):
        if n in short:
            if n in do_rows:  # the numbered steps under the fact table are this Do's
                do, step, column = True, 0, 0
            elif len(line) - len(line.lstrip()) < column:
                do, step = False, 0
            continue
        if not line.strip() or DRAFT.match(line):
            continue
        marker = STEP.match(line) if do or step else None
        if marker:
            step = marker.end()
            continue
        if step and len(line) - len(line.lstrip()) >= step:
            continue
        if DO.search(line):
            item = ITEM.match(line)
            column = item.end() if item else 1
        do, step = bool(DO.search(line)) or (do and line[:1].isspace()), 0
        name = ITEM_LEAD.match(line)
        if name and not listed(name.group(1).strip()):  # a fact label, such as Do, is a note
            items.append([line])
            lead = ITEM.match(line).end()
            continue
        if lead and len(line) - len(line.lstrip()) >= lead and not ITEM.match(line):
            items[-1].append(line)  # the item's wrapped line
            continue
        lead = 0
        kept.append(line)
    # Up to TABLE_ROWS items, each a bold name and a clause within ITEM_SEND_BACK words,
    # are a fact table in list form, so like a short table they don't count. A longer item
    # or list, and the details under an item, count.
    free = len(items) <= TABLE_ROWS
    return kept + [line for item in items if not free or clause(item) > ITEM_SEND_BACK for line in item]


def count(lines):
    return sum(1 for line in lines for token in line.split() if WORD.search(token))


def clause(item):
    """The words of an item after its bold name."""
    return count([ITEM_LEAD.sub("", item[0]), *item[1:]])


def words(reply):
    """How many words the glance holds. A scope-grill round counts its own way: see
    grill_words."""
    if grill_round(reply):
        return grill_words(reply)
    return count(glance(reply))


# The round format's fixed labels, which scope-grill's budget leaves out (decision D-R13-2).
LABELS = re.compile(r"\*\*(?:Proposed this round|Changed this round|The plan so far|Building|Not building|Assuming"
                    r"|Size|Pick)(?::\*\*|\*\*:?)|\*my suggestion, not agreed\*|\(say if wrong\)"
                    r"|\((?:you|me)(?:,\s*rounds?\s*[\d–-]+)?\)|(?<=^[+\- ])\s*Size\s*:", re.M)
SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.S)


def grill_round(reply):
    """True when the reply shows a scope-grill plan: a **The plan so far** line outside code
    and tables."""
    lines = bare_references.visible(reply, blank_code=True)
    cell = {n for start, end, _ in tables(lines) for n in range(start, end)}
    return any(line.strip().startswith("**The plan so far**") for n, line in enumerate(lines) if n not in cell)


def grill_words(reply):
    """Scope-grill's glance: the prose above the round's fold, counting plan items and the
    fold's summary, but not code or diff blocks, short tables outside the plan, or the
    format's fixed labels. A plan fenced as a diff still counts: on Oct 30 a replay hid 233 plan words in diff fences, which a
    code-free count missed."""
    text = turn_block.lines_ended(reply)
    at = text.rfind("<!--")
    if at >= 0 and turn_block.BLOCK.match(text, at):
        text = text[:at]
    lines = text.split("\n")
    fences = turn_block.in_fence(lines)
    shown = ["" if fenced else line for line, fenced in zip(lines, fences)]
    short = views(shown)
    cell = {n for start, end, _ in tables(shown) for n in range(start, end)}  # never a round heading
    kept, plan = [], False
    for n, (line, fenced) in enumerate(zip(lines, fences)):
        if fenced:
            if plan and not FENCE.match(line):
                kept.append(line)
            continue
        stripped = line.strip()
        if n not in cell:  # a table cell is never a round heading, a fold, or the closing
            if stripped.startswith("**The plan so far**"):
                plan = True
            elif stripped.startswith("**Pick**"):
                plan = False
            if stripped.startswith("<details"):
                summary = SUMMARY.search(line)
                kept.append(summary.group(1) if summary else "")
                break
            if stripped == "---" or CLOSING.match(stripped):
                break
        if stripped and not DRAFT.match(line) and not (n in short and not plan):
            kept.append(line)
    prose = LABELS.sub(" ", "\n".join(kept))
    return sum(1 for token in prose.split() if WORD.search(token))


PLAN_END = re.compile(r"^(?:<details|\*\*(?:Pick|Next|Done)\*\*|---\s*$)")


def plan_fenced(reply):
    """Lines inside code fences between **The plan so far** and the Pick, outside folds.
    The plan is plain lists; only Proposed and Changed this round are diff blocks."""
    lines = bare_references.FOLD.sub("", reply).split("\n")
    kept, inside = [], False
    for line, fenced in zip(lines, turn_block.in_fence(lines)):
        if not fenced:
            if line.strip().startswith("**The plan so far**"):
                inside = True
            elif inside and PLAN_END.match(line.strip()):
                break
        elif inside and not FENCE.match(line):
            kept.append(line)
    return kept


def running(reply):
    """True when the reply's turn block says background work is still running."""
    try:
        return turn_block.parse(reply).state == "running"
    except turn_block.Malformed:
        return False


def opted_out(event):
    """True when a message of the user's this session opens by asking for normal replies."""
    path = event.get("transcript_path")
    return bool(path) and any(OPT_OUT.match(text.strip()) for text in transcripts.user_messages(path))


PLAN = re.compile(r"(?ms)^\*\*The plan so far\*\*.*?(?=^<details|^\*\*Pick\*\*|^---|\Z)")
SIZE = re.compile(r"(?m)^\s*(?:[-*]\s*)?\*\*Size: ?\*\*\s*(.+?)\s*$|^\s*(?:[-*]\s*)?\*\*Size\*\*\s*:\s*(.+?)\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def diff_blocks(reply):
    """Yield top-level diff blocks, excluding examples inside other fences or folds."""
    fence, block = None, None
    for line in bare_references.FOLD.sub("", reply).splitlines():
        marker = FENCE.match(line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                if block is not None:
                    yield "\n".join(block)
                fence, block = None, None
            elif block is not None:
                block.append(line)
        elif marker:
            fence = marker.group(1)
            block = [] if marker.group(2).strip() == "diff" else None


def plan_size(reply):
    plan = PLAN.search("\n".join(bare_references.visible(reply)))
    if not plan or not all(re.search(rf"\*\*{name}:?\*\*", plan.group())
                           for name in ("Building", "Not building", "Assuming")):
        return None
    match = SIZE.search(plan.group())
    return next((part.strip() for part in match.groups() if part), None) if match else None


VALUE = r"(?:[≈~]?\d+(?:[–-]\d+)?|unsettled|undecided|not estimated|no)"
# A unit may carry one qualifier word, as in `2 stacked PRs`, `≈3 new files`, `1 proposed migration`.
UNIT = r"(?:[a-z][\w-]*\s+)?(PRs?|files?|migrations?|lines?)\b"
DIMENSIONS = re.compile(rf"({VALUE})\s*{UNIT}", re.I)


def counts(text):
    """Each Size dimension's value, such as {"file": "4"}; a trail gives its last step."""
    found = {unit.lower().rstrip("s"): ("0" if number.lower() == "no" else number.lstrip("≈~").lower())
             for number, unit in DIMENSIONS.findall(text)}
    if re.search(r"migrations?\s+(?:unsettled|undecided)", text, re.I):
        found["migration"] = re.search(r"migrations?\s+(unsettled|undecided)", text, re.I).group(1).lower()
    if re.search(r"lines?\s+not estimated", text, re.I):
        found["line"] = "not estimated"
    return found


def missing_size_change(reply, previous):
    old, new = plan_size(previous), plan_size(reply)
    if not old or not new:
        return False
    old, new = old.replace("≈", "~"), new.replace("≈", "~")
    # Only a dimension counted in both rounds can change: rewording ("pending" to "unresolved")
    # and a first count after an unknown one need no trail, since a trail needs a known start.
    before, after = counts(old), counts(new)
    if old == new or all(before[unit] == after[unit] for unit in before.keys() & after.keys()):
        return False
    # The plan's own Size line may carry the trail, as in `~4 → ~6 files`.
    for block in [*diff_blocks(reply), "Size: " + new if "→" in new else ""]:
        block = block.replace("≈", "~")
        removed = re.findall(r"(?m)^-\s*Size\s*:\s*(.+?)\s*$", block)
        added = re.findall(r"(?m)^\+\s*Size\s*:\s*(.+?)\s*$", block)
        # Pairs can omit unchanged dimensions, but must cover every changed part.
        def parts(value):
            return {re.sub(r"^proposed\s+", "", part.strip(), flags=re.I) for part in value.split("·")}
        before, after = parts(old), parts(new)
        if removed and added and before - after <= parts(" · ".join(removed)) and after - before <= parts(" · ".join(added)):
            return False
        for trail in re.findall(r"(?m)^\s*[+ ]?\s*Size\s*:\s*(.+?)\s*$", block):
            steps = [part.strip() for part in trail.split("→")]
            if len(steps) > 1 and steps[0] == old and steps[-1] == new:
                return False
            # A trail may name only changed dimensions, including file ranges.
            before, after = counts(old), counts(new)
            changes = {unit: (before[unit], after[unit]) for unit in before.keys() & after.keys()
                       if before[unit] != after[unit]}
            trail = re.sub(r"migrations?\s+(unsettled|undecided)\s*→", r"\1 →", trail, flags=re.I)
            trail = re.sub(r"lines?\s+not estimated\s*→", "not estimated →", trail, flags=re.I)
            arrows = re.findall(rf"({VALUE}(?:\s*→\s*{VALUE})+)\s*{UNIT}", trail, re.I)
            shown = {unit.lower().rstrip("s"): tuple("0" if step.strip().lower() == "no" else step.strip().lstrip("≈~").lower() for step in steps)
                     for chain, unit in arrows if len(steps := chain.split("→")) > 1}
            for first, unit, last, end_unit in re.findall(rf"({VALUE})\s*{UNIT}\s*→\s*({VALUE})\s*{UNIT}", trail, re.I):
                key = unit.lower().rstrip("s")
                if key == end_unit.lower().rstrip("s"):
                    shown[key] = (first.lstrip("≈~").lower(), last.lstrip("≈~").lower())
            # A trail shows a change from its start or from its last step.
            if changes and all(unit in shown and change in {(shown[unit][0], shown[unit][-1]), shown[unit][-2:]}
                               for unit, change in changes.items()):
                return False

    return True


ASSUMING = re.compile(r"^\s*(?:[-*]\s*)?\*\*Assuming\*\*\s*(?:\(say if wrong\))?\s*:?\s*(.*)$")
TAGS = re.compile(r"\((?:pending|checked|you|me)\b[^)]*\)", re.I)
# A clause that is only a pointer: "audit's Q2–Q13 defaults", "defaults", "see the report", "+4 more in the fold".
POINTER = re.compile(r"^(?:the\s+)?(?:[\w-]+(?:'s)?\s+)?(?:Q\d+\s*[–-]\s*Q?\d+\s*)?(?:defaults?)?$"
                     r"|^(?:see|per|as in)\s+(?:the\s+)?(?:report|audit|fold)\b.*$|^\+?\s*\d+\s+more\b.*$", re.I)


def pointer_assuming(reply):
    """True when the round's **Assuming** line names no value, only a pointer such as
    "audit defaults" or "Q2–Q13 defaults". "none" is a value."""
    lines = bare_references.FOLD.sub("", reply).split("\n")
    inside = False
    for line, fenced in zip(lines, turn_block.in_fence(lines)):
        if fenced:
            continue
        if line.strip().startswith("**The plan so far**"):
            inside = True
        elif inside and PLAN_END.match(line.strip()):
            return False
        match = ASSUMING.match(line) if inside else None
        if match:
            value = TAGS.sub(" ", match.group(1)).strip(" .")
            clauses = [c.strip(" .") for c in re.split(r"[;,]", value) if c.strip(" .")]
            return bool(clauses) and all(POINTER.match(c) and re.search(r"\w", c) for c in clauses)
    return False


PICK = re.compile(r"^\s*(?:[-*]\s+)?\*\*Pick\*\*")
# A **Source** label, as **Source**, **Sources**, or **Source, verified**: a line's lead (a heading
# or list item's too), or a label with its colon, as in "… **Source**: README.md:115"; not a
# mention such as "the **Source** field", a **Source files** label, or one in inline code.
SOURCE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+)?\*\*Sources?(?:,[^*\n]*)?:?\*\*"
                    r"|\*\*Sources?(?:,[^*\n]*)?(?::\*\*|\*\*\s*:)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
# What a Pick line can cite itself: a URL, a path:line, a named doc, or an ADR or decision id.
CITES = re.compile(r"https?://\S|[\w./-]+\.\w+:\d+|[\w.-]+(?:/[\w.-]+)+:\d+|[\w./-]*\w\.mdx?\b|\bADR[-\s]?\d+|\bdocs/adr/\S*\w|\bD-[\w-]*\d", re.I)
BARE_PICK = re.compile(r"^\s*(?:[-*]\s+)?\*\*Pick\*\*:?\s*$")
# A blank line, a list item, a heading, a quote, or a new label such as **Cost**: ends the
# Pick's paragraph; a wrapped line that opens in bold, such as **reply-shape/SKILL.md**., doesn't.
PARAGRAPH_END = re.compile(r"^\s*(?:$|[-*+]\s|\d+[.)]\s|#{1,6}\s|>|\*\*[^*\n]+(?::\*\*|\*\*\s*:))")
SOURCE_FEEDBACK = ("This decision card's **Pick** cites no source. Add a **Source** naming the doc, ADR, "
                   "path:line, URL, or measurement the pick follows, then resend the whole reply.")


def unsourced(reply):
    """True when the reply is a decision card, its recommended option a decision, with a
    visible **Pick** that cites nothing itself and no **Source** label above the closing.
    A fact table's Pick and Source rows count as those labels. A ship gate, post, or push
    passes, since its view carries the checks."""
    try:
        turn = turn_block.parse(reply)
    except turn_block.Malformed:
        return False
    if turn.state != "stop" or not turn.recommended or turn.recommended.cls != "decision":
        return False
    shown = bare_references.visible(reply, blank_code=True)
    picks = [n for n, line in enumerate(shown) if PICK.match(line)]
    fact = fact_table(reply)
    rows = {name: [row.value for row in fact.rows if listed(row.label, (name,))] if fact else []
            for name in ("Pick", "Source")}
    if not picks and not rows["Pick"]:
        return False
    if rows["Source"] or any(CITES.search(value) for value in rows["Pick"]):
        return False
    text = turn_block.lines_ended(reply)
    lines = text[:text.rfind("<!--")].split("\n")
    closings = [n for n, line in enumerate(lines) if line.strip() == "---" or CLOSING.match(line.strip())]
    above = lines[:closings[-1] if closings else len(lines)]
    labels = (INLINE_CODE.sub("", line) for line, code in zip(above, turn_block.in_fence(above)) if not code)
    if any(SOURCE.search(line) for line in labels):
        return False
    return not any(CITES.search(line) for n in picks for line in pick_lines(shown, n))


def pick_lines(shown, n):
    """The Pick at line n: its line and the lines that wrap it, or, under a bare **Pick**
    label, the list that follows, as scope-grill numbers its picks."""
    if not BARE_PICK.match(shown[n]):
        end = next((m for m in range(n + 1, len(shown)) if PARAGRAPH_END.match(shown[m])), len(shown))
        return shown[n:end]
    kept, m = [shown[n]], n + 1
    while m < len(shown):
        line = shown[m]
        if not line.strip():  # a loose list keeps going past a blank line to its next item
            ahead = next((later for later in shown[m + 1:] if later.strip()), "")
            if not (ITEM.match(ahead) or ahead[:1].isspace()):
                break
        elif not (ITEM.match(line) or line[:1].isspace()):
            break
        kept.append(line)
        m += 1
    return kept


# A merge the option asks for, "merge #12" or "start merging #12", not one it leaves to the user or
# rules out: "I'll merge them myself" or "don't merge" after marking ready.
MERGES = re.compile(r"\bmerg(?:e|es|ed|ing)\b", re.I)
NOT_ASKED = re.compile(r"(?:\bI'll|\bI will|\bdon't|\bdo not|\bnot|\bnever|\bwithout)\s+(?:\w+\s+){0,2}$", re.I)


def asks_merge(text):
    """True when the option's text asks for a merge rather than leaving or ruling one out."""
    text = text.replace("’", "'")
    return any(not NOT_ASKED.search(text[:match.start()]) for match in MERGES.finditer(text))


def unplain(reply):
    """The reply's merge options whose text merge_go doesn't read as a literal go."""
    try:
        options = turn_block.parse(reply).options
    except turn_block.Malformed:
        return []  # routine_stop.py sends a reply without a valid block back
    return [option for option in options
            if option.cls == "stop:merge" and asks_merge(option.text)
            and not merge_go.literal_go(option.text)]


def merge_feedback(reply):
    """The send-back text for merge options merge-gate wouldn't take as a go, or None."""
    found = unplain(reply)
    if not found:
        return None
    listing = "; ".join(f"`{option.key}` → {option.text}" for option in found)
    return (f"These merge options aren't the plain request merge-gate takes as the user's go: {listing}. "
            "Write each as the merge alone, such as \"merge #12 and #13\", with any step before or after it "
            "in the reply or another option, the same in Next and the turn block, then resend the whole reply.")


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active"):
        return
    # A child whose brief says "Reply rules: on" plays the user's session, so it gets sent back too.
    if bare_references.delegated_child(event) and not t3_child.rules_on(bare_references.first_brief(event)):
        return
    reply = event.get("last_assistant_message") or ""
    # The merge option is a contract merge-gate reads, so "normal replies" doesn't turn it off.
    shape = () if running(reply) or opted_out(event) else (
        problem(event, reply), fact_feedback(reply), SOURCE_FEEDBACK if unsourced(reply) else None)
    # One send per stop, so a fact table's limits and a missing source ride along with any other problem.
    feedback = " ".join(filter(None, (*shape, merge_feedback(reply))))
    if feedback:
        send_back(event, feedback)


def problem(event, reply):
    """The send-back text for the reply's shape, or None when it passes."""
    exchanges = transcripts.exchanges(event.get("transcript_path") or "")
    previous = exchanges[-1].reply if exchanges else None
    if previous and missing_size_change(reply, previous):
        return "The plan's Size changed without showing the change. Write it as a trail on the plan's Size line, such as `~4 → ~6 files`, then resend the whole reply."
    if grill_round(reply) and pointer_assuming(reply):
        return ("The round's **Assuming** line points at a report or its defaults instead of naming them. "
                "Name the assumed values that change what gets built, such as `Apple Pay in cards; "
                "biometrics in auth (pending)`, with the rest as `+N more in the fold`, then resend the whole round.")
    count = words(reply)
    if grill_round(reply):
        return grill_feedback(reply, count) if over(count) else None
    if count <= SEND_BACK:
        return None
    return (
        f"Your reply's headline and notes come to {count} words; reply-shape keeps them under {BUDGET}. The user "
        "reads each reply at a glance. Send your whole reply again as one, in the shape your reply rules give: "
        "a headline of at most 12 words, then its fact table, or a bold item per thing with its details in the fold and its risks and reader items under it, or under rules without one the one view that fits "
        "the content or none and at most three notes of at most 15 words, and the same closing and turn block. Keep every risk, decision, and step the user must take, "
        "and move checks and evidence to the one fold. T3 shows only a turn's last message and folds the rest "
        "away, so the resent reply has to stand on its own. Add no note about the change.")


def grill_feedback(reply, count):
    fenced = ("Write The plan so far as plain lists: only Proposed this round and Changed this round "
              "are diff blocks. ") if plan_fenced(reply) else ""
    return fenced + (
        f"This scope-grill round has {count} words of prose above its fold; scope-grill keeps it under "
        f"{BUDGET} and aims for about 45. The fixed labels and the code and diff blocks are free; plan "
        "items and the fold's summary count. Send the whole round again with shorter clauses: fold older "
        "Building clauses by name, and move detail into the fold. Keep every question, pick and Next "
        "option. Add no note about the change.")


def send_back(event, feedback):
    if "turn_id" in event:
        print(json.dumps({"decision": "block", "reason": feedback}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))



if __name__ == "__main__":
    main()

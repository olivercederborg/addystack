# Copy of skills/primitive/addystack/hooks/turn_block.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""Parses the turn block every final reply ends with: `<!-- turn {json} -->`, the
reply's state, what it needs from the user, and its Next options with each one's class.
An optional `standing` list, in the same item shape, holds the user's items still open
from earlier replies that don't block this turn's next step; ids are unique across both
lists, and nothing that reads attention or a stop counts it.

Hooks used to read the reply's English with regexes to decide whether option `a` was
routine, or whether a prompt asked for a merge. The stakes are the user's typing: they
answered a bare `a` 1,636 times in October 2026 (36.7% of their typed messages), and 66% of
1,726 `a` picks since Sep 28 were routine. A typed block makes "is `a` a stop?" and "did
they pick a merge?" lookups instead of guesses. The block is prefrontal-turns' base, which
Prefrontal reads, plus addystack's extensions, which the kit's references/turn-block.md
spells out, or the Turn block section of the user's reply rules file when they keep one.

The block is an HTML comment so the user never sees it: T3 Code renders markdown through
rehype-raw, then rehype-sanitize, which drops comment nodes, and an unclosed `<!--` while
the reply streams is a comment to the end of input. So the body can't hold `-->` or
`--!>`, either of which ends the comment early and shows the rest.

It must be the last non-whitespace text of the reply, outside any code block, and the
only one there: a block in a code block or a code span is an example, and a second one
outside makes the reply Malformed. It starts at column 0 of its own line, which per
CommonMark 0.31.2 puts it at the top level, since `<!--` starts an HTML block that
interrupts a paragraph. A line reader can tell whether a top-level fence holds it only
when it can place every fence line, so `picked` returns None for a reply with a fence
marker after a list marker or `>`, indented 4+ or by a tab, or in an indented fence a less
indented line may end with its list item: merge-gate reads a pick as a merge go, and a
refused one costs the user a typed go. Raw HTML can hide the block in three ways, and a
pick counts only when the lines outside fences before it, inline code included, since a
code span doesn't hide a `<` once a link destination eats its backtick, hold none of them:
- An element the renderer reads by HTML's rules, not CommonMark's, as text to its end tag:
  a start tag of `script`, `style`, `textarea`, `title`, `xmp`, `iframe`, `noembed`,
  `noframes`, `noscript`, or `plaintext`, or of `pre`, whose CommonMark HTML block runs to
  `</pre>` past any fence. So does any `<!` or `<?`: a comment, CDATA, or declaration. A
  `<table>` or one of its parts moves what follows it out of the table and leaves the block
  inside it, so the block is no longer the reply's last node, and the renderer drops a
  `<template>`'s content. A `<details>` fold still open at the block shows the options
  above it collapsed, and inside a `<select>`, `<object>`, `<applet>`, `<marquee>`, `<svg>`,
  or `<math>` the parser may ignore the `</details>` that closes it.
- A line that starts an HTML block, past list and quote markers, with no blank line after
  it: the block runs to the next blank line, so the lines after it are raw HTML, not fences.
  A block tag such as `<div` starts one, as does a whole tag alone on its line (CommonMark
  0.31.2 §4.6). Any other line starting with a tag holds only attribute-free formatting
  tags (PLAIN), such as `<sub>…</sub><br>`.
- A line whose tag the WHATWG tokenizer hasn't closed at the line's end, such as
  `<div title="x`, when it starts an HTML block or a line follows it: what follows
  becomes the tag's attribute.
Other tags, such as `<code>` in a fold's summary or `Option<T>` in inline code, are safe:
CommonMark reads inline HTML only as a whole tag, which ends where HTML's tokenizer ends it.
Known limit: an unsafe tag in a code span that does hold it, such as `<table>`, refuses
too, since a line reader can't prove the span; 0 of 308 merge picks since Nov 1, 2026 had one.
T3's session importer
shows the reply after JS `trim()`, so a pick needs the block certain both as written and
trimmed, with the same options. Known limits: code spans are read line by line, so one that
wraps onto the next line doesn't hide a mention there, and a record with more than one
text part is joined untrimmed here but trimmed part by part by the importer, which 0 of
26,386 assistant records did in 14 days. `in_fence` is the fence reader check_examples.py
shares."""
from __future__ import annotations

import json, re
from dataclasses import dataclass
from typing import Literal, get_args

MARK = "<!-- turn "

State = Literal["stop", "done", "running"]
Kind = Literal["decide", "review", "do"]
Class = Literal["routine", "decision", "stop:merge", "stop:push", "stop:post", "stop:prod", "stop:credential"]

# A fence opens with 3+ backticks or tildes after 0-3 spaces; a backtick fence's info string
# has no backtick.
OPENER = re.compile(r"( {0,3})(`{3,}(?=[^`]*$)|~{3,})")
# A fence marker after any indent and container prefixes ("- ", "1. ", "> ").
MARKER = re.compile(r"([ \t>]*(?:(?:[-+*]|\d{1,9}[.)])[ \t>]*)*)(?:`{3}|~{3})")
# Raw HTML that reads what follows as text or as markup to its own end, anywhere on a line.
UNSAFE = re.compile(r"<(?:[!?]|(?:script|style|textarea|title|xmp|iframe|noembed|noframes|noscript|plaintext|pre|"
                    r"table|caption|colgroup|col|tbody|thead|tfoot|tr|td|th|template|select|object|applet|marquee|"
                    r"svg|math)(?=[\t\f />]|$))", re.I)
OPENS_FOLD = re.compile(r"<details(?=[\t\f />]|$)", re.I)
# A line that starts a `<details>` HTML block: raw HTML to its end, with no code spans in it.
FOLD_LINE = re.compile(r" {0,3}</?details(?=[\t\f />]|$)", re.I)
# A line that starts an HTML block, past list and quote markers, by CommonMark 0.31.2 §4.6's
# start condition 6, a block tag name (micromark's htmlBlockNames) then whitespace, the
# line's end, > or />, or 7, one whole open or closing tag
# with only whitespace after it. Whitespace is any \s, as markdown-it-py reads it, wider
# than micromark's spaces and tabs. UNSAFE holds conditions 1 to 5.
BLOCK_NAMES = ("address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|"
               "div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|"
               "li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|"
               "tbody|td|tfoot|th|thead|title|tr|track|ul")
ATTRIBUTE = r"""\s+[A-Za-z_:][\w.:-]*(?:\s*=\s*(?:[^"'=<>`\x00-\x20]+|'[^']*'|"[^"]*"))?"""
HTML_START = re.compile(rf"[ \t>]*(?:(?:[-+*]|\d{{1,9}}[.)])[ \t>]*)*<(?:/?(?:{BLOCK_NAMES})(?=\s|/?>|$)"
                        rf"|(?:[A-Za-z][A-Za-z0-9-]*(?:{ATTRIBUTE})*\s*/?|/[A-Za-z][A-Za-z0-9-]*\s*)>\s*$)", re.I)
# A line that starts with a tag, past list and quote markers, but not with a URI autolink
# (CommonMark 0.31.2 §6.5, without a backtick, so it can't pair with a code span).
AUTOLINK = r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\x00-\x20<>`\x7f]*>"
LEADS = re.compile(rf"[ \t>]*(?:(?:[-+*]|\d{{1,9}}[.)])[ \t>]*)*<(?!{AUTOLINK[1:]})[A-Za-z/]")
# Inline tags that format text and hide none of it, such as the reviewer-reply disclosure's.
PLAIN = re.compile(r"</?(?:sub|sup|br|wbr|b|i|em|strong|code|kbd|s|del|ins|mark|small)\s*/?>", re.I)
TAG = re.compile(r"</?[A-Za-z]")
SPACE = "\t\n\f "
CARRIER = re.compile(r"<!--\s*turn\b")
TICKS = re.compile(r"`+")
BLOCK = re.compile(r"<!--\s*turn\b\s*(.*?)\s*-->\s*\Z", re.S)
# Exactly one key, which "option" may lead ("Option A"), and marks around it (“a”, a ✅),
# but no question mark: "a?" is a question, not a pick, and so is "a？" or "a؟". QUESTIONS
# holds every character whose Unicode name says QUESTION, so no script's question passes.
QUESTIONS = ("?\u00bf\u037e\u055e\u061f\u1367\u1945\u2047\u2048\u2049\u225f\u2370\u2753\u2754\u2a7b"
             "\u2a7c\u2cfa\u2cfb\u2e2e\u2e54\u3244\ua60f\ua6f7\ufe16\ufe56\uff1f\U00011143\U0001e95f"
             "\U0001fbc4\U000e003f")
AROUND = rf"[^\w{QUESTIONS}]"
PICK = re.compile(rf"{AROUND}*(?:option\s+)?([abc]){AROUND}*", re.I)
WORD = re.compile(r"[^\W\d_]{3}")
# Exactly what JS trim() drops: ECMAScript WhiteSpace and LineTerminator.
JS_SPACE = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
            "\u2028\u2029\u202f\u205f\u3000\ufeff")


@dataclass(frozen=True)
class Need:
    id: int  # >= 1, unique; the number the visible Needs you list gives it
    kind: Kind
    name: str  # 1-80 characters, with a word of 3+ letters


@dataclass(frozen=True)
class Option:
    key: str  # "a", "b", "c", in order
    cls: Class  # "class" in the JSON
    text: str  # 1-400 characters


@dataclass(frozen=True)
class Turn:
    state: State
    needs: tuple[Need, ...]
    options: tuple[Option, ...]
    eta: str | None  # running only, and only when measured
    elapsed: str | None  # running only
    project: str | None = None  # 1-40 characters; threads that share it group into one row
    # Items still open from earlier replies that don't block this turn's next step. They
    # never count as needing the user: attention reads needs only.
    standing: tuple[Need, ...] = ()

    @property
    def recommended(self) -> Option | None:
        return self.options[0] if self.options else None

    @property
    def items(self) -> tuple[Need, ...]:
        """Every user item the reply lists, needs then standing, for naming an id."""
        return self.needs + self.standing


class Malformed(ValueError):
    """A reply with no valid turn block. str(error) is the reason, one line, such as 'no
    turn block at the end of the reply' or 'options[1].class "merge" is not one of …'."""


def in_fence(lines):
    """For each line, whether it's in a code block, its fences included, read as top-level
    lines by CommonMark's fence rules. An unclosed fence runs to the end, as Markdown
    renders it."""
    return scan(lines)[0]


def scan(lines):
    """in_fence's marks for lines, and whether they and the raw HTML before the last
    top-level turn block line are certain. Certain is False when a fence marker sits where
    a container may hold it, or a line outside fences holds raw HTML that may hide the
    block, as the module docstring says."""
    marks, sure, fence, indent = [], True, None, 0
    for line in lines:
        if fence:
            marks.append(True)
            # A line left of an indented opener may end the list item that holds the fence.
            sure = sure and not line[:indent].strip()
            if re.match(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", line):
                fence = None
            continue
        marker, opener = MARKER.match(line), OPENER.match(line)
        if marker and (marker.group(1).strip(" ") or len(marker.group(1)) > 3):
            sure = False
        marks.append(bool(opener))
        if opener:
            indent, fence = len(opener.group(1)), opener.group(2)
    top = max((at for at, line in enumerate(lines) if not marks[at] and CARRIER.match(line)), default=len(lines))
    # A fold still open at the block holds it, and the options above it, collapsed. Any
    # `<details` may open one, but only a `</details>` the tokenizer reads on a line that
    # starts a fold's HTML block surely closes one: elsewhere it may sit in a code span.
    depth = 0
    for at in range(top):
        line = lines[at]
        folds = [] if marks[at] else [closing for closing, name in tags(line) if name == "details"] \
            if FOLD_LINE.match(line) else [False] * len(OPENS_FOLD.findall(line))
        for closing in folds:
            depth = max(depth - 1, 0) if closing else depth + 1
    sure = sure and not depth
    for at in range(top):
        line = lines[at]
        after = lines[at + 1] if at + 1 < len(lines) else ""
        starts, follows = HTML_START.match(line), after.strip(" \t")
        # A tag left open at the line's end runs on, as an HTML block's raw HTML or as an
        # inline tag whose attribute takes the paragraph's next line, and a line that starts
        # with a tag other than PLAIN ones may hide what follows, as `<h2 class="sr-only">`.
        if not marks[at] and (UNSAFE.search(line) or starts and follows or not closed(line) and (starts or follows)
                              or LEADS.match(line) and not starts and not plain(line)):
            sure = False
    return marks, sure


def plain(line):
    """Whether each tag on line, past autolinks, is a PLAIN one with no attributes."""
    at = 0
    while (at := line.find("<", at)) >= 0:
        link, tag = re.compile(AUTOLINK).match(line, at), TAG.match(line, at)
        found = None if link or not tag else PLAIN.match(line, at)
        if tag and not link and not found:
            return False
        at = (link or found).end() if link or found else at + 1
    return True


def tags(line):
    """(closing, name) for each tag in line, in order, as the WHATWG tokenizer reads it from
    its data state, up to one it can't end on the line."""
    at = 0
    while (at := line.find("<", at)) >= 0:
        if TAG.match(line, at):
            closing = line[at + 1] == "/"
            name = re.match(r"[^\t\n\f />]*", line[at + 1 + closing:]).group().lower()
            at = tag_end(line, at + 1 + closing)
            if at is None:
                return
            yield closing, name
        else:
            at = (line.find(">", at + 2) + 1 or len(line)) if line.startswith("</", at) else at + 1


def closed(line):
    """Whether the WHATWG tokenizer, reading line from its data state, is back in it at the
    line's end: every tag it opens ends with a > outside a quoted attribute value, and every
    `</` that starts no end tag, a bogus comment, at the next >."""
    at = 0
    while (at := line.find("<", at)) >= 0:
        if TAG.match(line, at):
            at = tag_end(line, at + (2 if line[at + 1] == "/" else 1))
        elif line.startswith("</", at):
            at = line.find(">", at + 2) + 1 or None
        else:
            at += 1
        if at is None:
            return False
    return True


def tag_end(line, at):
    """Where the tag whose name starts at line[at] ends, just past its >, by the WHATWG
    tokenizer's tag states (HTML 13.2.5.8 to 13.2.5.40), or None when the line ends first."""
    state = "name"
    while at < len(line):
        char = line[at]
        # The states that hand the character on to another one unread.
        if state == "self-closing" and char != ">" or state == "after value" and char not in SPACE + "/>":
            state = "before attribute"
            continue
        if state in ("before attribute", "attribute") and char in "/>" or state == "attribute" and char in SPACE:
            state = "after attribute"
            continue
        if state == "before value" and char not in SPACE + "\"'>":
            state = "unquoted"
            continue
        if state in ("double", "single"):
            state = "after value" if char == ('"' if state == "double" else "'") else state
        elif char == ">":
            return at + 1
        elif char in SPACE:
            state = "before attribute" if state in ("name", "unquoted", "after value") else state
        elif char == "/" and state in ("name", "after attribute", "after value"):
            state = "self-closing"
        elif char == "=" and state in ("attribute", "after attribute"):
            state = "before value"
        elif char in "\"'" and state == "before value":
            state = "double" if char == '"' else "single"
        elif state in ("before attribute", "after attribute"):
            state = "attribute"  # an = here starts a name too
        at += 1
    return None


def carriers(line):
    """Where blocks start on a line outside code blocks, skipping code spans, as Markdown
    reads them left to right: a run of backticks opens a span that the next run of the same
    length closes, and a `<!--` that comes first is a comment, backticks and all."""
    found, at = [], 0
    while True:
        carrier, ticks = CARRIER.search(line, at), TICKS.search(line, at)
        if carrier and (not ticks or carrier.start() < ticks.start()):
            found.append(carrier.start())
            at = carrier.end()
        elif not ticks:
            return found
        else:
            close = re.compile(f"(?<!`){ticks.group()}(?!`)").search(line, ticks.end())
            at = close.end() if close else ticks.end()


def show(value):
    """A value as one short line of JSON, for a reason."""
    text = json.dumps(value)
    return text if len(text) <= 40 else text[:37] + "..."


def unique(pairs):
    found = {}
    for key, value in pairs:
        if key in found:
            raise Malformed(f"field {show(key)} appears twice")
        found[key] = value
    return found


def constant(name):
    raise Malformed(f"not JSON: {name}")


def lines_ended(text):
    """text as the renderer reads its lines: one leading byte-order mark dropped, and
    CommonMark's other line endings, CRLF and a lone CR, as LF."""
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def block_body(reply):
    """The JSON text of the reply's one turn block; raises Malformed."""
    return located(reply)[1].group(1)


def before_block(reply):
    """The reply's text before its turn block, line endings as lines_ended writes them: what
    the user sees above it. Raises Malformed."""
    text, block = located(reply)
    return text[:block.start()]


def quiet(reply):
    """Whether the reply is its turn block alone, as a quiet wake's is: the user sees none of
    it, so the card on screen is still the reply above it."""
    try:
        return not before_block(reply).strip()
    except Malformed:
        return False


def located(reply):
    """(lines_ended(reply), the BLOCK match of its one turn block); raises Malformed."""
    if not isinstance(reply, str):
        raise Malformed("no turn block at the end of the reply")
    reply = lines_ended(reply)
    starts, offset = [], 0
    lines = reply.split("\n")
    for line, fenced in zip(lines, in_fence(lines)):
        if not fenced:
            starts += [offset + at for at in carriers(line)]
        offset += len(line) + 1
    if not starts:
        raise Malformed("no turn block at the end of the reply")
    if len(starts) > 1:
        raise Malformed("more than one turn block")
    # Any indent or text before it puts it in a container or a paragraph: an example.
    if starts[0] and reply[starts[0] - 1] != "\n":
        raise Malformed("the turn block must start at the beginning of its own line")
    block = BLOCK.match(reply, starts[0])
    if not block:
        closed = "-->" in reply[starts[0]:]
        raise Malformed("the turn block is not the last thing in the reply" if closed
                        else "the turn block is not closed with -->")
    if "-->" in block.group(1) or "--!>" in block.group(1):
        raise Malformed("the turn block holds --> or --!>, which ends the comment early")
    return reply, block


def read_fields(value, where, required, optional=()):
    """value as a dict holding every required field and no unknown one; a field may be in both."""
    if not isinstance(value, dict):
        raise Malformed(f"{where or 'the turn block'} is not a JSON object")
    prefix = f"{where}." if where else ""
    for key in value:
        if key not in (*required, *optional):
            raise Malformed(f"unknown field {show(prefix + key)}")
    for key in required:
        if key not in value:
            raise Malformed(f"missing field {show(prefix + key)}")
    return value


def one_of(value, allowed, where):
    if value not in allowed:  # list and dict values compare unequal to every string
        raise Malformed(f"{where} {show(value)} is not one of {', '.join(allowed)}")
    return value


def read_text(value, where, longest, rule=None):
    if not isinstance(value, str) or not value.strip() or len(value) > longest or (rule and not rule.search(value)):
        extra = " with a word of 3+ letters" if rule else ""
        raise Malformed(f"{where} must be text of 1-{longest} characters{extra}")
    return value


def read_list(value, where):
    if not isinstance(value, list):
        raise Malformed(f"{where} is not a list")
    return value


def read_need(value, at, ids, field="needs"):
    """An item of field, needs or standing; ids maps each id read so far to its list, since
    an id is unique across both."""
    where = f"{field}[{at}]"
    value = read_fields(value, where, ("id", "kind", "name"))
    number = value["id"]
    if type(number) is not int or number < 1:
        raise Malformed(f"{where}.id {show(number)} is not a whole number of 1 or more")
    if number in ids:
        earlier = "an earlier need" if ids[number] == "needs" else "an earlier standing item"
        raise Malformed(f"{where}.id {number} repeats {earlier}")
    ids[number] = field
    return Need(number, one_of(value["kind"], get_args(Kind), f"{where}.kind"),
                read_text(value["name"], f"{where}.name", 80, WORD))


def read_option(value, at):
    where = f"options[{at}]"
    value = read_fields(value, where, ("key", "class", "text"))
    if value["key"] != "abc"[at]:
        raise Malformed(f"{where}.key {show(value['key'])} should be \"{'abc'[at]}\"")
    return Option(value["key"], one_of(value["class"], get_args(Class), f"{where}.class"),
                  read_text(value["text"], f"{where}.text", 400))


def load(reply):
    """The reply's turn block's JSON value; raises Malformed with the reason."""
    body = block_body(reply)
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=constant)
    except Malformed:
        raise
    except (ValueError, RecursionError) as error:  # Python 3.9 recurses on deep nesting
        raise Malformed(f"not JSON: {' '.join(str(error).split())}") from None


def read_options(value):
    """value's options list, checked as parse checks it; a missing one is ()."""
    listed = read_list(value.get("options", []), "options")
    if len(listed) > 3:
        raise Malformed(f"options has {len(listed)} items, at most 3")
    return tuple(read_option(item, at) for at, item in enumerate(listed))


def options(reply: str) -> tuple[Option, ...]:
    """The reply's turn block's options, for a reader that needs only them, as the gates
    that take a pick as a go do: the block's place, its JSON, and its options list are
    checked as parse checks them, and no other field is read. In the two weeks to Nov 26,
    2026, 432 of 9,094 blocks failed parse, 418 of them only on a field no gate reads,
    mostly a standing name over 80 characters or a missing needs, and a pick of one read
    as no pick. Raises Malformed with the reason."""
    value = load(reply)
    if not isinstance(value, dict):
        raise Malformed("the turn block is not a JSON object")
    return read_options(value)


def parse(reply: str) -> Turn:
    """The reply's turn block as a Turn; raises Malformed with the reason."""
    value = load(reply)
    # A missing list reads as [] on running and done, where [] is the only valid options and
    # done's only valid needs. A stop still names both, since merge-gate reads its picks from
    # them and a forgotten list there goes back. An explicit null is still not a list.
    lists = () if isinstance(value, dict) and value.get("state") in ("running", "done") else ("needs", "options")
    value = read_fields(value, "", ("state", *lists), ("needs", "options", "eta", "elapsed", "project", "standing"))
    state = one_of(value["state"], get_args(State), "state")
    ids = {}
    needs = tuple(read_need(item, at, ids) for at, item in enumerate(read_list(value.get("needs", []), "needs")))
    standing = tuple(read_need(item, at, ids, "standing")
                     for at, item in enumerate(read_list(value.get("standing", []), "standing")))
    options = read_options(value)
    # eta stays optional, as in prefrontal-turns, since only a measured one helps the user.
    if state == "running" and "elapsed" not in value:
        raise Malformed("state running needs elapsed")
    for field in ("eta", "elapsed"):
        if state != "running" and field in value:
            raise Malformed(f"state {state} carries {field}")
        if field in value:
            read_text(value[field], field, 40)
    if "project" in value:
        read_text(value["project"], "project", 40)
    if state == "running" and options:
        raise Malformed("state running carries options")
    if state == "done" and (options or needs):
        raise Malformed(f"state done carries {'options' if options else 'needs'}")
    # standing is allowed with every state, and alone it doesn't make a stop.
    if state == "stop" and not (options or needs):
        raise Malformed("state stop has no options or needs")
    return Turn(state, needs, options, value.get("eta"), value.get("elapsed"), value.get("project"), standing)


def certain(view):
    """view's turn block options, read by options(), when scan is certain of its lines and
    they read, else None; () is a block with no options."""
    if not scan(lines_ended(view).split("\n"))[1]:
        return None
    try:
        return options(view)
    except Malformed:
        return None


def picked(reply: str | None, prompt: str) -> Option | None:
    """The option the prompt picks from the reply's block: None when the reply is None, its
    block isn't certain, with the same options, both as written and after JS trim(), the
    prompt isn't exactly one key ("a", " A. "; not "a, skip 3" or "a?"), or the block has no
    option with that key."""
    match = PICK.fullmatch(prompt) if isinstance(prompt, str) and isinstance(reply, str) else None
    found = certain(reply) if match else None
    if found is None or found != certain(reply.strip(JS_SPACE)):
        return None
    return next((option for option in found if option.key == match.group(1).lower()), None)

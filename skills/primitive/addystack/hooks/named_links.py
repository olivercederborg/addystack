"""Finds the issue and PR ids a Markdown text cites without a link whose text names
them, as reply-shape's "Links that name" asks: `[DEV-3127, Allow failure-only export
emails](https://linear.app/…)`, once a text. Owns every rule about it: what text is
visible (not code, not HTML comments, which hide the turn block), what counts as an id
(a Linear-style `ABC-123` that isn't a standard such as UTF-8, `#N`, `repo#N`), and what
counts as named (a link whose text holds the id and words). named-links-notice.py reads
replies with it, and scripts/check_examples.py the kit's example replies.

It reads Markdown with regexes, not a CommonMark parser, since hooks use the standard
library only. Known limits, none of which any of 6,241 final replies in the 14 days to
Nov 25, 2026 hit: indented code reads as prose, since a list item's continuation looks
the same; a fence inside an HTML comment counts as a fence; link text holding brackets
isn't a link; a reference link counts without its definition; a label such as "View PR
#9" names it; and a digit-only color such as #333, unless a colon comes right before it,
reads as a PR."""
import re
from typing import List, NamedTuple

from turn_block import lines_ended

# Standards and versions written like a Linear id, such as UTF-8, SHA-256, or GPT-4.
STANDARDS = {"UTF", "SHA", "GPT", "ISO", "CVE", "RFC", "ADR", "AES", "RSA", "TLS", "SSL", "PEP", "UTC", "GMT",
             "HTTP", "IPV", "ES", "ECMA", "WCAG"}
# A code span: a backtick run, then the text up to the next run of the same length.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)
# A fence line: after any indent, quote markers, and list markers, three or more backticks
# or tildes, as in a fence nested in a list item ("- ```text").
FENCE = re.compile(r"^(?:\s*(?:>|[-*+]\s|\d+[.)]\s))*\s*(`{3,}|~{3,})")
# [text](destination "title"), allowing one level of parentheses in the destination, or
# a reference link, [text][label].
LINK = re.compile(r"\[([^\[\]\n]*)\](\(\s*(?:<[^>\n]*>|(?:[^()\s]|\([^()\s]*\))*)"
                  r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)|\[[^\[\]\n]*\])")
URL = re.compile(r"<?\b(?:https?|ftp)://[^\s<>`]*>?|\bwww\.[^\s<>`]+")
# DEV-3127; owner/repo#12 or repo#12, a repo name of one character too; #12, before any
# punctuation, as in "#13; then". A number with a leading zero, as in #000, is a hex
# color, and so is one right after a colon (color:#333); an & before # starts an HTML
# entity (&#123;). C# and F# take no number.
ID = re.compile(r"(?<![\w-])(?P<team>[A-Z]{2,6})-(?P<issue>[1-9]\d*)(?![\w-])"
                r"|(?<![\w./-])(?P<repo>(?:[A-Za-z0-9][\w.-]*/)?[A-Za-z0-9](?:[\w.-]*[A-Za-z0-9_])?)"
                r"#(?P<pull>[1-9]\d*)(?![\w-])"
                r"|(?<![\w&#:])#(?P<number>[1-9]\d*)(?![\w-])")
WORD = re.compile(r"[^\W\d_]{2,}")
# Words that say what an id is, not what it does: "[PR #9](…)" names nothing.
GENERIC = {"pr", "pull", "request", "issue", "ticket", "link", "see", "here", "this", "the"}


class Cited(NamedTuple):
    id: str    # as first written: "DEV-3127", "#124", "dotfiles#12"
    line: int  # the 0-based line of text that first cites it


def blank(match):
    """The match's text with every character but a newline as a space, so offsets and
    line numbers stay where they were."""
    return re.sub(r"[^\n]", " ", match.group(0))


def key(match):
    """What an id names: ("issue", "DEV", 3127), ("pull", "acme/app", 7),
    ("pull", "dotfiles", 12), or ("pull", "", 12) for a bare #12. None for a standard such
    as UTF-8."""
    if match.group("team"):
        team = match.group("team")
        return None if team in STANDARDS else ("issue", team, int(match.group("issue")))
    if match.group("repo"):
        return ("pull", match.group("repo").lower(), int(match.group("pull")))
    return ("pull", "", int(match.group("number")))


def names(link_text):
    """The ids a link's text names: each id in it, when it also holds a word of two or
    more letters that says what it is about, as in "[#12, Login](…)"."""
    if not any(word.lower() not in GENERIC for word in WORD.findall(ID.sub(" ", link_text))):
        return set()
    return {found for found in map(key, ID.finditer(link_text)) if found}


def same_repo(repo, other):
    """True when two repo names can name one repo: the same name, and the same owner
    unless one leaves it out, so acme/app and app match but acme/app and other/app don't."""
    owner, _, name = repo.rpartition("/")
    other_owner, _, other_name = other.rpartition("/")
    return name == other_name and (not owner or not other_owner or owner == other_owner)


def covered(cited, named):
    """True when a named id covers this one: the same id; for a bare #12, any repo's #12;
    for app#12, a named app#12 under any owner, or the same owner's. A named #12 doesn't
    cover dotfiles#12, which may be another repo's."""
    kind, repo, number = cited
    return cited in named or (kind == "pull" and any(
        other[0] == "pull" and other[2] == number and (not repo or other[1] and same_repo(repo, other[1]))
        for other in named))


def fenced(lines):
    """For each line, True when it is a fence line or inside a fenced code block. Unlike
    turn_block.in_fence, which refuses a fence it can't place, this places one anywhere
    a reader sees it: nested in a list item or a quote, or indented."""
    marks, fence = [], None
    for line in lines:
        found = FENCE.match(line)
        if fence is None and found:
            fence = found.group(1)
            marks.append(True)
        elif fence is not None:
            if found and found.group(1)[0] == fence[0] and len(found.group(1)) >= len(fence) \
                    and not line[found.end():].strip():
                fence = None
            marks.append(True)
        else:
            marks.append(False)
    return marks


def visible(text):
    """text with what a reader doesn't read as prose blanked: fenced code, code spans, and
    HTML comments (the turn block is one), in that order, so a `<!--` shown in code hides
    nothing. Line breaks stay, so lines keep their number."""
    lines = lines_ended(text).split("\n")
    text = "\n".join("" if fence else line for line, fence in zip(lines, fenced(lines)))
    return COMMENT.sub(blank, CODE_SPAN.sub(blank, text))


def unnamed(text: str) -> List[Cited]:
    """Each id text cites in visible prose with no link anywhere in text that names it,
    once, in the order first cited. A link's destination and a bare URL cite nothing."""
    prose = visible(text)
    named = set()
    for link in LINK.finditer(prose):
        named |= names(link.group(1))
    prose = LINK.sub(lambda link: f"[{link.group(1)}]" + re.sub(r"[^\n]", " ", link.group(2)), prose)
    prose = URL.sub(blank, prose)
    found, seen = [], set()
    for match in ID.finditer(prose):
        cited = key(match)
        if cited and cited not in seen and not covered(cited, named):
            seen.add(cited)
            found.append(Cited(match.group(0), prose.count("\n", 0, match.start())))
    return found

"""Whether a prompt, or a reply option's text, is a literal merge go: a short request whose
only action is the merge, matched whole. merge-gate.py takes a PR with no checks on one.

A go names what to merge or nothing: "merge it", "merge both stacks please", "merge #92
through #112 into main", "merge dotfiles#1", "merge #55 and dotfiles #36", "lets get the
final PRs merged", "merge whats ready now and merge the rest when they come back done".
It may open on a pick of the reply's option ("a, and merge them"), on marking the PRs
ready, or on a polite opener, end on "please", a following pick, "and start next", or "we
can always change it back", and ask as "can you" or "let's" ("lets merge it?"). A
question about whether to merge, "can we merge …?" included, a refusal, an if-clause
first, another step before or after the merge (fix, push, rebase, verify, deploy,
release, try it out, handle it), and talk about merging don't match, though a refusal or
step NOT_REPO misses before a "#N" reads as a repo (REPO_REF). MergeGo in test_hooks.py
holds the real prompts this was built from, each with its source: every one merge-gate
denied for want of a go, and the nearest misses."""
import re

from project_md import NOT_REPO  # the words that name no repo, shared with Workers cells

# A repo's name before " #N", as in "dotfiles #36", but no word a sentence puts there:
# "merge after #36" waits, "merge #55, skip #36" refuses, "merge #55 and fix #36" adds a
# step, and "PR #36", "stack #3", or "merge 5 #36" names no repo. No list holds every such
# word, so merge-gate.py holds a go that names a repo to the PRs it names (REPO_NAMED).
# push-gate.py reads the same names, so a push step ("restack #6091") names no repo either.
REPO = rf"(?!{NOT_REPO}\s)(?:[\w.-]+/[\w.-]+|[\w.-]*[a-z][\w.-]*)"  # owner/12306 or 1password, not 55
REPO_REF = re.compile(rf"(?<![^\s(,&-])({REPO})\s+(?=#\d)", re.I)  # the repo word of "dotfiles #36"
# Whether a text names a PR with its repo: "dotfiles #36", dotfiles#36, sam/12306#36, or
# #10-dotfiles#14, but not #53-#55.
REPO_NAMED = re.compile(rf"{REPO_REF.pattern}|(?<![#\w./])(?:[\w.-]+/[\w.-]+|[\w.-]*[a-z][\w.-]*)#\d", re.I)
REF = rf"(?:(?:[\w.-]+/)?[\w.-]+#\d+|{REPO}\s+#\d+|#?\d+)"
REFS = rf"{REF}(?:(?:\s*[,&-]\s*|\s+(?:and|through|to)\s+){REF})*"
STATE = r"(?:ready|passing|green|safe|done|verified)"
TARGET = (rf"(?:\s+(?:it(?: all)?|them(?: all|,? the (?:full|whole) list)?|both(?: open)?(?: prs| stacks)?|all(?: of them)?"
          rf"|everything|anything|whats? ready|the rest|this(?: pr| one)?|{REFS}"
          rf"|the (?:(?:whole )?stacks?(?: of {REFS})?|\d+(?: prs?)?|prs?|(?:full|whole) list)"
          rf"|(?:all )?(?:the )?(?:open |current |final )?prs(?: for the [\w-]+)?"
          rf"|(?:all )?(?:the (?:ready )?ones|those(?: (?:ready )?(?:ones|prs))?))"
          rf"(?:\s+that (?:are|is) {STATE}(?: to (?:be merged|merge))?|\s+that can be merged)?)?")
WHEN = (r"(?:\s+for me)?(?:\s+(?:now|right now|instantly|in that order|(?:with|using) gh stack))?"
        r"(?:\s+into `?main`?)?"
        rf"(?:\s+(?:when|once|if)\s+(?:(?:it'?s|it is|they'?re|they are|they)\s+)?(?:{STATE}|pass|come back {STATE})(?: ci)?"
        r"(?: and ci passes)?)?")
CORE = rf"(?:merge{TARGET}|get{TARGET} merged){WHEN}"
CORES = rf"{CORE}(?:,?\s+and\s+(?:then\s+)?{CORE})*"
PICK = r"`?[abc]`?"
LEAD = rf"(?:{PICK}\s*(?:,\s*and|,|\+|and)\s+|mark (?:it|them|the prs?) ready(?: for review)? and\s+)"
OPENER = r"(?:(?:please|just|ok(?:ay)?|yes|sure|great|sounds good|looks good|lgtm|so|go ahead and|let'?s)[,\s]+)*"
ASK = r"(?:(?:can|could) you|let'?s)\s+(?:please\s+)?(?:just\s+)?"
TAIL = (rf"\s*(?:,\s*then|,|->|and(?: then)?(?: proceed with)?)\s+{PICK}|\s+and start (?:the )?next"
        r"|(?:,|\s+and)(?: then)? we can always (?:change|revert|undo) it(?: back)?")
LITERAL_GO = re.compile(rf"{OPENER}{LEAD}?(?:{OPENER}{CORES}|{ASK}{LEAD}?{CORES}\??)(?:{TAIL})?(?:,?\s+please)?[.!]?", re.I)


def literal_go(text):
    # A go is short; the cap also keeps the lead runs from going quadratic on a paste.
    return len(text) <= 200 and LITERAL_GO.fullmatch(text.strip().replace("’", "'")) is not None


# A PR a text names, read word by word in REF's forms: 12, #12, skills#12,
# owner/skills#12, skills #12 read as skills#12, and 10-14 or #10-#14. Two joined by
# "through", "to", or "-" are a range. "the 2 PRs" is a count, and "v2" a name, not a PR;
# a bare "the 13" reads as #13.
PART = r"(?:(?:([\w.-]+)/)?([\w.-]+)#|#)?(\d+)"
WORD = re.compile(rf"{PART}(?:-{PART})?")
COUNT = re.compile(r"\bthe \d+ prs?\b", re.I)


def spans(text):
    """(spans, unread): the PRs text names, in order, each a range of two ends (repo,
    number), with repo an (owner or None, name) pair or None for a bare end, and a lone PR a
    range of one. unread is None, or the (word, why) that stops the read: a word that starts
    like a PR, with a digit or holding a #, but doesn't read as one, or a range chained onto
    another, as "#10 through dotfiles #12 through #14", which can hide its middle end's repo."""
    text = REPO_REF.sub(r"\1", text)  # "dotfiles #36" reads as dotfiles#36
    text = re.sub(r"\s*-\s*", "-", COUNT.sub(" ", text)).replace(",", " ").replace("&", " ")  # REFS joins
    words = [word.strip("()").rstrip(".!?;:") for word in text.split()]
    refs = []
    for at, word in enumerate(words):
        if not (word[:1].isdigit() or "#" in word):
            continue
        found = WORD.fullmatch(word)
        if not found:
            return [], (word, "doesn't read as a PR or a range of two")
        refs.append((at, found))
    end = lambda found, at: ((found.group(at), found.group(at + 1)) if found.group(at + 1) else None,
                             int(found.group(at + 2)))
    read, last = [], None  # last: the previous PR word's index and whether its span is a range
    for at, found in refs:
        low = end(found, 1)
        high = end(found, 4) if found.group(6) else low
        joined = bool(last) and last[0] == at - 2 and words[at - 1].lower() in ("through", "to", "-")
        if joined and (last[1] or found.group(6)):
            return [], (words[at], "chains a range onto another")
        if joined:
            read[-1] = (read[-1][0], high)  # "#10 through #14" is one range, not three
        else:
            read.append((low, high))
        last = (at, joined or bool(found.group(6)))
    return read, None


def names(text, pr, owner, repo, merging=()):
    """Whether an option's text names pr in owner/repo, alone or in a range of this repo's
    PRs, or names no PR at all ("merge them"). A PR with its repo, "dotfiles #36" or
    dotfiles#36, is in that repo. A bare one, "#55", is in any repo, unless another PR in the
    text names this repo, so "#55" beside "dotfiles #36" isn't a dotfiles PR, and a range's
    bare end is in its other end's repo. A bare PR after one that names a repo, as #12 in
    "merge dotfiles #36 and #12", may be in that repo, so it's in none. A text that places a
    PR the merge holds (pr and merging) in another repo, or in none, names none: the word
    before it may be a refusal or a step NOT_REPO misses, as in "merge #10-#14, exclude #12",
    and so does a text that names a repo and names one PR twice. A word that starts like a
    PR, with a digit or holding a #, but doesn't read as one, names something it can't place,
    so it isn't pr. merge-gate.py holds a go to it."""
    read, unread = spans(text)
    if unread:
        return False
    same = lambda part, want: not part or part.lower() == want.lower()
    # Each end: whether its repo is this one, or None when it names no repo.
    here = lambda end: None if end[0] is None else same(end[0][0], owner) and same(end[0][1], repo)
    found = [tuple((here(point), point[1]) for point in span) for span in read]
    bare = not any(here_ for span in found for here_, _ in span)
    side = lambda one, other: one if one is not None else other if other is not None else bare
    after_repo = [any(point[0] is not None for span in found[:i] for point in span) for i in range(len(found))]
    placed = [(side(a[0], b[0]) and side(b[0], a[0]) and not (a[0] is None and b[0] is None and late), a[1], b[1])
              for (a, b), late in zip(found, after_repo)]
    held = lambda low, high: any(min(low, high) <= n <= max(low, high) for n in {pr, *merging})  # "#14-#12" too
    if any(not ours and held(low, high) for ours, low, high in placed):
        return False
    # A text that names a repo and names a PR twice may refuse it the second time, even
    # with this repo's name: "merge exclude #10-#14, exclude #12" in a repo named exclude.
    spread = [(min(low, high), max(low, high)) for _, low, high in placed]
    if any(point[0] is not None for span in found for point in span) and any(
            max(a[0], b[0]) <= min(a[1], b[1]) for i, a in enumerate(spread) for b in spread[i + 1:]):
        return False
    return not found or any(ours and low <= pr <= high for ours, low, high in placed)


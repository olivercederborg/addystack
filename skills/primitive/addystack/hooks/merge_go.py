"""Whether a prompt, or a reply option's text, is a literal merge go: a short request whose
only action is the merge, matched whole. merge-gate.py takes a PR with no checks on one.

A go names what to merge or nothing: "merge it", "merge both stacks please", "merge #92
through #112 into main", "merge dotfiles#1", "merge #55 and dotfiles #36", "lets get the
final PRs merged", "merge whats ready now and merge the rest when they come back done". It may open on a pick of the
reply's option ("a, and merge them"), on marking the PRs ready, or on a polite opener, end
on "please", a following pick, "and start next", or "we can always change it back", and
ask as "can you" or "let's" ("lets merge it?"). A question about whether to merge, "can
we merge …?" included, a refusal, an if-clause first, another step before or after the
merge (fix, push, rebase, verify, deploy, release, try it out, handle it), and talk about
merging don't match. MergeGo in test_hooks.py holds the real prompts this was built from,
each with its source: every one merge-gate denied for want of a go, and the nearest misses."""
import re

# A repo's name before " #N", as in "dotfiles #36", but no word a sentence puts there:
# "merge after #36" waits, "merge except #36" refuses, and "PR #36", "stack #3", or
# "merge 5 #36" names no repo.
NOT_REPO = (r"(?:after|before|until|till|once|when|then|than|but|except|not|without|with|on|onto|into|in|from"
            r"|for|of|by|to|through|and|or|only|just|also|both|all|the|it|them|this|that|these|those"
            r"|prs?|pull|issues?|stacks?|branch|merge)")
REPO = rf"(?!{NOT_REPO}\s)(?:[\w.-]+/)?[a-z][\w.-]*"
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

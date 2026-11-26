"""Whether a prompt, or a reply option's text, is a literal push go: a short request to push
that says it dismisses an approval, matched whole, as merge_go.py is for a merge.
push-gate.py takes a push that dismisses an approval on one that names each PR it dismisses.

A go's whole shape is built as merge_go.LITERAL_GO is, from fixed lists so no free words
fit: merge_go's OPENER, then push steps, each a verb with its PRs (merge_go.REFS), it, or
the stack, and a branch it goes onto, then last the dismissal of whose approval: "push
#6119 (dismisses the teammate's approval)", "ok, restack and push #6091, dismissing …",
never "push #6119 tomorrow (dismisses …)" or "push #6119 is risky, it dismisses …". The
dismissal may name the PRs whose approval goes, each with its #: "push all five PRs,
dismissing the teammate's approvals on #6179 and #6213". plain_go reads the same request
without the dismissal, which push-gate.py takes only right after a reply whose stop:push
option is a go for the same dismissals."""
import re
from typing import NamedTuple

import merge_go

# A count of PRs names none of them: "all five PRs", "both PRs".
COUNTED = r"(?:all(?: the)?(?: (?:\d{1,2}|two|three|four|five|six|seven|eight|nine|ten))?|both|the) prs"
# The branch a push goes onto, which it doesn't push: "onto develop", "restacked on develop".
BASE = r"\s+(?:(?:restacked|rebased)\s+(?:on|onto|on top of)|onto|on top of)\s+`?[\w./-]+`?"
STEP = (rf"(?:force-?push|push|restack|re-stack|rebase|sync|submit)"
        rf"(?:\s+(?:it|them|both|the (?:stack|branch)|{COUNTED}|{merge_go.REFS}))?(?:{BASE})?")
# Whose approval: logins and words, a login may hold a digit (reviewer2) but no word is a PR
# (PR 6215, pr6215, #6215), and a count is at most two digits ("2 approvals").
WHOSE = r"(?:(?:the|their|its|both)\s+)?(?:(?:(?!pr\W?\d)[A-Za-z@][\w.@-]*|\d{1,2})(?:'s)?,?\s+(?:and\s+)?){0,5}"
# The PRs whose approval goes, each with its #, so no count reads as one: "on #6179 and #6213".
DREF = rf"(?:(?:[\w.-]+/)?[\w.-]+#\d+|{merge_go.REPO}\s+#\d+|#\d+)"
DREFS = rf"(?:prs?\s+)?{DREF}(?:(?:\s*[,&]\s*|,?\s+and\s+){DREF})*"
ON = rf"(?:\s+(?:on|of|for)\s+(?P<dismissed>{DREFS}))?"
DISMISSAL = (rf"(?:\s*\(\s*dismiss(?:es|ing)?\s+{WHOSE}approvals?{ON}\s*\)"
             rf"|(?:,\s*(?:it\s+|which\s+)?|,?\s+and\s+)dismiss(?:es|ing)?\s+{WHOSE}approvals?{ON.replace('dismissed', 'listed')})")
# Routine steps may follow the dismissal, each a verb and what it acts on, ending on a reply,
# thread, comment, review, CI, or description, never a PR: "push #6203 (dismisses the
# teammate's approval), then post 3 replies, resolve both threads", but not "…, post the reply
# and skip the push", or "…, post the reply on #6216".
NOUN = r"(?:repl(?:y|ies)|threads?|comments?|reviews?|ci|checks?|descriptions?)"
NAME = r"[A-Za-z@.'_-]+"  # no digit, so no PR
AFTER_STEP = (rf"(?:(?:post|reply|answer|resolve|comment|re-?request|re-?verify|verify|watch|re-?run|run|update)"
              rf"(?:(?:\s+(?:the|both|all|its|their|this|that))?(?:\s+\d{{1,2}})?(?:\s+{NAME}){{0,2}}?\s+{NOUN})?"
              rf"(?:\s+(?:on|to|in|for)\s+{NAME}(?:\s+{NOUN})?)?|re-?request\s+{NAME}(?:\s+review)?)")
AFTER = rf"(?:\s*[,;]\s*(?:then\s+)?|,?\s+and\s+(?:then\s+)?){AFTER_STEP}"
PUSH = rf"(?:yes:\s*)?{merge_go.OPENER}(?P<push>{STEP}(?:(?:,\s*|,?\s+and\s+(?:then\s+)?){STEP})*)"
GO = re.compile(rf"{PUSH}{DISMISSAL}(?:{AFTER})*[.!]?", re.I)
PLAIN = re.compile(rf"{PUSH}(?:{AFTER})*[.!]?", re.I)
# A request with any of these may refuse, wait, ask, or only describe what the push would do,
# so it's no go: a question opens with its verb or asks word even without its ?.
REFUSAL = re.compile(r"\?|\b(?:\w+n't|\w+'ll|dont|wont|cant|shouldnt|do not|never|not|no|without|avoid|unless|if|until|"
                     r"wait|hold|stop|after|once|when|whenever|before|whether|later|will|would|could|might|shall)\b|^\W*(?:is|are|was|were|will|"
                     r"would|could|can|should|shall|does|do|did|has|have|had|may|might|must|why|what|how|where|"
                     r"which|who)\b", re.I)


class Go(NamedTuple):
    push: str  # the push steps, before the dismissal
    dismissed: str  # the PRs the dismissal names, or ""


def read(pattern, text):
    text = text.strip().replace("’", "'")
    return len(text) <= 200 and not REFUSAL.search(text) and pattern.fullmatch(text)


def literal_go(text):
    """text's Go when it is a short typed request to push that says it dismisses an
    approval, else None."""
    found = read(GO, text)
    return Go(found.group("push"), found.group("dismissed") or found.group("listed") or "") if found else None


def plain_go(text):
    """The push steps of text when it is literal_go's request without the dismissal, else None."""
    found = read(PLAIN, text)
    return found.group("push") if found else None

"""Whether a prompt, or a reply option's text, is a literal push go: a short request to push
that says it dismisses an approval, matched whole, as merge_go.py is for a merge.
push-gate.py takes a push that dismisses an approval on one that names each PR it dismisses.

A go's whole shape is built as merge_go.LITERAL_GO is, from fixed lists so no free words
fit: merge_go's OPENER, then push steps, each a verb with its PRs (merge_go.REFS), it, or
the stack, and a branch it goes onto, then last the dismissal of whose approval: "push
#6119 (dismisses the teammate's approval)", "ok, restack and push #6091, dismissing …",
never "push #6119 tomorrow (dismisses …)" or "push #6119 is risky, it dismisses …"."""
import re

import merge_go

STEP = (rf"(?:force-?push|push|restack|re-stack|rebase|sync|submit)(?:\s+(?:it|them|both|the (?:stack|branch)|{merge_go.REFS}))?"
        r"(?:\s+(?:onto|on top of)\s+`?[\w./-]+`?)?")
# Whose approval: logins and words, a login may hold a digit (reviewer2) but no word is a PR
# (PR 6215, pr6215, #6215), and a count is at most two digits ("2 approvals").
WHOSE = r"(?:(?:the|their|its|both)\s+)?(?:(?:(?!pr\W?\d)[A-Za-z@][\w.@-]*|\d{1,2})(?:'s)?,?\s+(?:and\s+)?){0,5}"
DISMISSAL = (rf"(?:\s*\(\s*dismiss(?:es|ing)?\s+{WHOSE}approvals?\s*\)"
             rf"|(?:,\s*(?:it\s+|which\s+)?|,?\s+and\s+)dismiss(?:es|ing)?\s+{WHOSE}approvals?)")
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
GO = re.compile(rf"(?:yes:\s*)?{merge_go.OPENER}(?P<push>{STEP}(?:(?:,\s*|,?\s+and\s+(?:then\s+)?){STEP})*){DISMISSAL}(?:{AFTER})*[.!]?",
                re.I)
# A request with any of these may refuse, wait, ask, or only describe what the push would do,
# so it's no go: a question opens with its verb or asks word even without its ?.
REFUSAL = re.compile(r"\?|\b(?:\w+n't|\w+'ll|dont|wont|cant|shouldnt|do not|never|not|no|without|avoid|unless|if|until|"
                     r"wait|hold|stop|after|once|when|whenever|before|whether|later|will|would|could|might|shall)\b|^\W*(?:is|are|was|were|will|"
                     r"would|could|can|should|shall|does|do|did|has|have|had|may|might|must|why|what|how|where|"
                     r"which|who)\b", re.I)


def literal_go(text):
    """The push steps of text, before its dismissal, when text is a short typed request to
    push that says it dismisses an approval, else None."""
    text = text.strip().replace("’", "'")
    found = len(text) <= 200 and not REFUSAL.search(text) and GO.fullmatch(text)
    return found.group("push") if found else None

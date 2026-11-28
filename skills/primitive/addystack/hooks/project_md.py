"""Reads what a coordinator's project.md (coordinator/references/project.md) names: its
thread links, its PR references, and its Workers table. coordinator/scripts/project.py,
which writes the file, and card-check.py, which reads it at Stop, share this module;
scripts/copies.txt copies it into coordinator/scripts."""
import re
from typing import NamedTuple

CELL = re.compile(r"(?<!\\)\|")  # a cell ends at a | that isn't escaped
LINK = re.compile(r"t3-thread://v2/([^/>\s)]+)/([^>\s)]+)")  # bare, in <…>, or a Markdown link's (…)
# A PR as its URL, owner/repo#N, repo#N (the checkout's owner), or #N (the checkout's repo).
PR_REF = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)|(?<![\w/.-])([\w.-]+(?:/[\w.-]+)?)#(\d+)\b"
                    r"|(?<![\w/#])#(\d+)\b")
THREAD_ROW = re.compile(r"(running|overdue|unknown)\b")  # a row whose thread should be running


def cells(row):
    return [cell.strip() for cell in CELL.split(row.strip())[1:-1]]


def ranges(text):
    """text with each range `#20–#22`, up to 20 apart, written out as `#20 #21 #22`."""
    return re.sub(r"(?<![\w/#])#(\d+)\s*[–-]\s*#?(\d+)\b", lambda m: " ".join(
        f"#{n}" for n in range(int(m[1]), int(m[2]) + 1)) if 0 < int(m[2]) - int(m[1]) <= 20 else m[0], text)


# `web #20` or `acme/web #20–#22`, but not a joining word, as in `#20 and #21` or `PR #12`
# A word before " #N" that names no repo, as in "merge after #36", "stack #3", or "#20 and #21".
# merge_go.py reads the same list, so a prompt and a Workers cell agree on what names a repo.
NOT_REPO = (r"(?:after|before|until|till|once|when|then|than|later|maybe|but|except|excluding|unless|not"
            r"|no|never|dont|skip|drop|ignore|hold|without|with|on|onto|into|in|from|for|of|by|to"
            r"|through|and|or|only|just|also|both|all|the|it|them|this|that|these|those|prs?|pull"
            r"|issues?|stacks?|branch|merge|fix|push|force-push|restack|sync|submit|rebase|revert|verify|deploy|release|review|close"
            r"|plus|see|blocked)")
# `web #20` or `acme/web #20–#22`: a repo word the tick can't resolve
UNREAD = re.compile(rf"(?<![\w/.#-])(?!(?i:{NOT_REPO})\s)[\w.-]*[^\W_][\w./-]*\s+#\d+(?:\s*[–-]\s*#?\d+)?\b")
LINKED = re.compile(r"\[[^\]\n]*\]\(<?([^()\s<>]*)>?(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\)")  # a link names its destination


CODE_PR = re.compile(r"(?:https?://)?github\.com/[\w.-]+/[\w.-]+/pull/\d+|[\w.-]+/[\w.-]+#\d+|#\d+")  # a PR in code, not a branch


class Pulls(NamedTuple):
    refs: tuple  # each PR the text names, as "owner/repo#N", once, in order
    unread: tuple  # each piece that reads as a PR but resolves to no repo, as written


ARROW = re.compile(r"\s*(?:→|->|=>|⟶)\s*")  # what joins a stack's PRs in a cell


def pulls(text, origin):
    """The PRs a Workers cell names, resolved against origin, the checkout's `owner/repo`.
    `#N`, and `repo#N` when repo is origin's own name, are origin's; `owner/repo#N` and a
    github.com PR URL name their own, a Markdown link by its destination; a range `#20–#22`
    names each. Refs are lowercased. A parenthesised note and a backticked branch name no PR,
    while a backticked PR ref or URL does. Unread: a word then `#N` (`web #20`), `repo#N` for
    another repo, since its owner is a guess, and `#N` when origin is "". A bare `#N` an arrow
    joins to the ref before it continues that ref's repo, as `owner/tools#109 → #110`, and is
    unread after an unread one."""
    text, origin = LINKED.sub(r" \1 ", text), origin.lower()
    text = re.sub(r"`([^`]*)`", lambda code: f" {code[1]} " if CODE_PR.fullmatch(code[1].strip()) else " ", text)
    while (bare := re.sub(r"\([^()]*\)", " ", text)) != text:  # innermost note first
        text = bare
    refs, unread = [], []
    for part in text.split(";"):
        words = iter(word[0] for word in UNREAD.finditer(part))
        marked = ranges(UNREAD.sub("\0", part))  # each unread word a NUL, so the order holds
        chain, end = None, 0  # the repo a bare #N an arrow joins continues: "owner/tools#109 → #110"
        for found in re.finditer(rf"\0|{PR_REF.pattern}", marked):
            if not ARROW.fullmatch(marked[end:found.start()]):
                chain = None
            end = found.end()
            if found[0] == "\0":
                unread.append(next(words))
                chain = ""
                continue
            url_repo, url_n, repo, n, local = (group or "" for group in found.groups())
            if url_repo or "/" in repo:
                chain = (url_repo or repo).lower()
                refs.append(f"{chain}#{url_n or n}")
            elif local and chain:
                refs.append(f"{chain}#{local}")
            elif local and chain == "":
                unread.append(f"#{local}")
            elif origin and (local or repo.lower() == origin.split("/")[1].lower()):
                chain = origin
                refs.append(f"{origin}#{n or local}")
            else:
                unread.append(f"{repo}#{n or local}")
                chain = ""
    return Pulls(tuple(dict.fromkeys(refs)), tuple(dict.fromkeys(unread)))


def workers(lines, start, end):
    """The Workers table in lines[start:end] as rows of {column: cell}, and the rows whose
    cells don't match the header."""
    table = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if len(table) < 2:
        return [], []
    header, rows, odd = cells(lines[table[0]]), [], []
    for i in table[2:]:
        found = cells(lines[i])
        if len(found) == len(header):
            rows.append(dict(zip(header, found)))
        else:
            odd.append(lines[i])
    return rows, odd

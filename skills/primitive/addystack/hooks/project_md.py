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


UNREAD = re.compile(r"(?<![\w/.#-])[\w.-]*[^\W_][\w./-]*\s+#\d+(?:\s*[–-]\s*#?\d+)?\b")  # `web #20`, `acme/web #20–#22`
LINKED = re.compile(r"\[[^\]\n]*\]\(([^()\s]*)\)")  # a Markdown link names its destination, not its label


class Pulls(NamedTuple):
    refs: tuple  # each PR the text names, as "owner/repo#N", once, in order
    unread: tuple  # each piece that reads as a PR but resolves to no repo, as written


def pulls(text, origin):
    """The PRs a Workers cell names, resolved against origin, the checkout's `owner/repo`.
    `#N`, and `repo#N` when repo is origin's own name, are origin's; `owner/repo#N` and a
    github.com PR URL name their own, a Markdown link by its destination; a range `#20–#22`
    names each. Refs are lowercased. A parenthesised note and a backticked branch name no PR. Unread: a word then `#N` (`web #20`), `repo#N`
    for another repo, since its owner is a guess, and `#N` when origin is ""."""
    text, origin = LINKED.sub(r" \1 ", text), origin.lower()
    while (bare := re.sub(r"\([^()]*\)|`[^`]*`", " ", text)) != text:  # innermost note first
        text = bare
    unread = [m[0] for m in UNREAD.finditer(text)]
    refs = []
    for url_repo, url_n, repo, n, local in PR_REF.findall(ranges(UNREAD.sub(" ", text))):
        if url_repo or "/" in repo:
            refs.append(f"{(url_repo or repo).lower()}#{url_n or n}")
        elif origin and (local or repo.lower() == origin.split("/")[1].lower()):
            refs.append(f"{origin}#{n or local}")
        else:
            unread.append(f"{repo}#{n or local}")
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

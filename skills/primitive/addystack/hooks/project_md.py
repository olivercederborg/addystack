"""Reads what a coordinator's project.md (coordinator/references/project.md) names: its
thread links, its PR references, and its Workers table. coordinator/scripts/project.py,
which writes the file, and card-check.py, which reads it at Stop, share this module;
scripts/copies.txt copies it into coordinator/scripts."""
import re

CELL = re.compile(r"(?<!\\)\|")  # a cell ends at a | that isn't escaped
LINK = re.compile(r"t3-thread://v2/([^/>\s)]+)/([^>\s)]+)")  # bare, in <…>, or a Markdown link's (…)
# A PR as its URL, owner/repo#N, repo#N (the checkout's owner), or #N (the checkout's repo).
PR_REF = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)|(?<![\w/.-])([\w.-]+(?:/[\w.-]+)?)#(\d+)\b"
                    r"|(?<![\w/#])#(\d+)\b")
THREAD_ROW = re.compile(r"(running|overdue|unknown)\b")  # a row whose thread should be running


def cells(row):
    return [cell.strip() for cell in CELL.split(row.strip())[1:-1]]


def ranges(text, bound=20):
    """text with each range `#20–#22`, up to bound apart, written out as `#20 #21 #22`."""
    return re.sub(r"(?<![\w/#])#(\d+)\s*[–-]\s*#?(\d+)\b", lambda m: " ".join(
        f"#{n}" for n in range(int(m[1]), int(m[2]) + 1)) if 0 < int(m[2]) - int(m[1]) <= bound else m[0], text)


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

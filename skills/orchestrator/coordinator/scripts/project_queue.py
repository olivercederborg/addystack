# Copy of skills/primitive/addystack/hooks/project_queue.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""A coordinator project's queue: every call and Do that waits on the user, in the `## Queue`
table of its project.md. The coordinator writes it only through `project.py queue`, and
coordinator_queue.py, a Stop hook, reads it to hold each reply in that thread to it.

Its replies used to carry the queue in the turn block alone, rewritten from memory each
turn, with the waiting calls in `standing`, a list the reply doesn't show. In the 14 days
to Nov 18, 2026, 10 of the 16 times the user typed "anything else waiting for me?" or
"what's next?" in a ◆ thread on one machine, the reply just before kept open calls there,
9 of them with `needs` empty; one call, "merge #39", sat there 8 days after #39 merged. A table that each
answer resolves gives the queue an owner, so a wake or a compaction finds it.

  | # | Kind | Name | From | Since |

`#` is the item's id, the one its turn-block need carries, never reused: the `Next id:`
line above the table holds the next one. Kind is `stuck`, a run the coordinator found
stuck, or a turn-block kind, `decide`, `review`, or `do`. Name is the turn block's need
name: 1-80 characters with a word of 3+ letters. From is the worker, with its thread
link, or `coordinator`. The user gets stuck runs first, then calls (decide and review),
then Do items, oldest first within each, as the coordinator skill's step 5 orders them."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime

import turn_block

HEADING = "## Queue"
COUNTER = "Next id: "
HEADER = ["#", "Kind", "Name", "From", "Since"]
KINDS = ("stuck", "decide", "review", "do")
RANK = {"stuck": 0, "decide": 1, "review": 1, "do": 2}
CELL = re.compile(r"(?<!\\)\|")
WORD = re.compile(r"[^\W\d_]{3}")  # turn_block.py's rule for a need's name
# The strip a reply carries while the queue holds an item: "1 of 3 need you · <its name> · <from>".
STRIP = re.compile(r"(?<!\d)(\d+) of (\d+) needs? you\b", re.I)


class QueueError(ValueError):
    """A queue edit or read that can't go as asked; str(error) says why."""


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    name: str
    source: str
    since: str

    def need(self) -> dict:
        """The item as a turn-block need: a stuck run is the user's call on it."""
        return {"id": self.id, "kind": "decide" if self.kind == "stuck" else self.kind, "name": self.name}


def _cells(row: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in CELL.split(row.strip())[1:-1]]


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def _bounds(lines: list[str]) -> tuple[int, int] | None:
    """The index of the Queue heading and of the line its section ends before, or None."""
    if HEADING not in lines:
        return None
    start = lines.index(HEADING)
    return start, next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))


def _table(lines: list[str], start: int, end: int) -> list[int]:
    rows = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if len(rows) < 2 or _cells(lines[rows[0]]) != HEADER:
        raise QueueError(f"the Queue table's header isn't {_row(HEADER)}: fix it by hand")
    return rows[2:]


def _item(row: str) -> Item:
    cells = _cells(row)
    if len(cells) != len(HEADER) or not cells[0].isdigit() or cells[1] not in KINDS:
        raise QueueError(f"a Queue row it can't read: {row.strip()!r}: fix it by hand")
    return Item(int(cells[0]), cells[1], cells[2], cells[3], cells[4])


def read(lines: list[str]) -> list[Item] | None:
    """The open items in the order the user gets them, or None when project.md has no
    Queue section yet. Raises QueueError on a table it can't read."""
    bounds = _bounds(lines)
    if bounds is None:
        return None
    items = [_item(lines[i]) for i in _table(lines, *bounds)]
    return sorted(items, key=lambda item: (RANK[item.kind], item.id))


def _one_line(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value.strip() or "\r" in value:
        raise QueueError(f"{name} takes one non-empty line")
    return value.strip()


def create(lines: list[str]) -> None:
    """Writes an empty Queue section before Decisions, or at the end, unless there is one."""
    if _bounds(lines) is None:
        at = lines.index("## Decisions") if "## Decisions" in lines else len(lines)
        lines[at:at] = [HEADING, "", f"{COUNTER}1", "", _row(HEADER), "|" + "---|" * len(HEADER), ""]


def add(lines: list[str], kind: str, name: str, source: str, now: datetime | None = None) -> Item:
    """Adds an item under the table and returns it. A project from before the queue has no
    section: `create` writes it, and only `project.py queue import` calls that, so the calls
    its last reply named arrive with the queue."""
    if kind not in KINDS:
        raise QueueError(f"kind {kind!r} isn't one of: {', '.join(KINDS)}")
    name, source = _one_line("the name", name), _one_line("--from", source)
    if len(name) > 80 or not WORD.search(name):
        raise QueueError("the name is 1-80 characters with a word of 3+ letters, as a turn-block need's is")
    if _bounds(lines) is None:
        raise QueueError("this project has no Queue yet: start it with `queue import`, which queues every item your "
                         "last reply named")
    start, end = _bounds(lines)
    rows = _table(lines, start, end)
    counter = next((i for i in range(start + 1, end) if lines[i].startswith(COUNTER)), None)
    if counter is None:
        raise QueueError(f"the Queue section has no `{COUNTER}<n>` line: fix it by hand")
    stored = lines[counter][len(COUNTER):].strip()
    # The counter, unless a hand edit left a row at or past it.
    ident = max([int(stored) if stored.isdigit() else 1, *(_item(lines[i]).id + 1 for i in rows)])
    item = Item(ident, kind, name, source, (now or datetime.now()).strftime("%Y-%m-%d %H:%M"))
    last = rows[-1] if rows else [i for i in range(start + 1, end) if lines[i].startswith("|")][1]
    lines.insert(last + 1, _row([str(item.id), item.kind, item.name, item.source, item.since]))
    lines[counter] = f"{COUNTER}{ident + 1}"
    return item


def done(lines: list[str], ident: int) -> Item:
    """Removes the item with this id and returns it."""
    bounds = _bounds(lines)
    if bounds is None:
        raise QueueError("project.md has no Queue section")
    for i in _table(lines, *bounds):
        item = _item(lines[i])
        if item.id == ident:
            del lines[i]
            return item
    raise QueueError(f"no open Queue item {ident}")


def shown(text: str) -> str:
    """text as a reply writes it: &, <, and > as entities outside each `<scheme:…>` link, so
    it renders as typed and leaves no raw < for merge-gate's pick reader to doubt."""
    parts, at = [], 0
    for link in turn_block.AUTOLINK.finditer(text):
        parts += [html.escape(text[at:link.start()], quote=False), link.group()]
        at = link.end()
    return "".join(parts + [html.escape(text[at:], quote=False)])


def strip(items: list[Item]) -> str:
    """The line a reply carries while the queue holds items: which one it shows of how many,
    that one's name, and where it came from."""
    return f"1 of {len(items)} need{'s' if len(items) == 1 else ''} you · {shown(items[0].name)} · {shown(items[0].source)}"


def as_json(value) -> str:
    """value as compact JSON a turn block can carry: < and > escaped, so a name holding
    `-->` can't end the block's comment early, and the parsed name stays the same."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


def show(items: list[Item] | None) -> str:
    """What `project.py queue show` prints: the strip and the top item's need, then each item."""
    if items is None:
        return ("This project has no Queue yet, so what waits on the user is unknown: start it with `queue import`, "
                "with a turn block naming every call still open on standard input.")
    if not items:
        return "Nothing waits on the user."
    listed = [f"  {item.id} {item.kind} · {item.name} · {item.source} · since {item.since}" for item in items]
    return "\n".join([strip(items), f"needs: [{as_json(items[0].need())}]", "queue:", *listed])

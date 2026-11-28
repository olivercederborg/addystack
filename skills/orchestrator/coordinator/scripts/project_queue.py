"""A coordinator project's queue: every call and Do that waits on the user, in the `## Queue`
table of its project.md. The coordinator writes it only through `project.py queue`.

Its replies used to carry the queue in the turn block alone, rewritten from memory each
turn, with the waiting calls in `standing`, a list the reply doesn't show. In the 14 days
to Nov 18, 2026, 10 of the 16 times the user typed "anything else waiting for me?" or
"what's next?" in a ◆ thread on one machine, the reply just before kept open calls there,
9 of them with `needs` empty; one call, "merge #39", sat there 8 days after #39 merged. A table that each
answer resolves gives the queue an owner, so a wake or a compaction finds it.

  | # | Kind | Name | From | Since | Batch |

`#` is the item's id, the one its turn-block need carries, never reused: the `Next id:`
line above the table holds the next one. Kind is `stuck`, a run the coordinator found
stuck, or a turn-block kind, `decide`, `review`, or `do`. Name is the turn block's need
name: 1-80 characters with a word of 3+ letters. From is the worker, with its thread
link, or `coordinator`. Batch, a column `add --batch` writes the first time one is given, is
the kind of call a card can share with others of its kind waiting at the same moment, such as
`post` or `merge:<stack>`: `show` puts the top item and each other item of its batch on one
card. On Nov 27, 2026 five review posts for one teammate took six separate goes over 95
minutes, and one coordinator showed 40 post cards in a day. The user gets stuck runs first,
then calls (decide and review), then Do items, oldest first within each, as the coordinator
skill's step 5 orders them, behind what waited a day under the user's priority line
(project.py's `priority`) and then the items it names."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Callable

import turn_block

HEADING = "## Queue"
COUNTER = "Next id: "
HEADER = ["#", "Kind", "Name", "From", "Since"]
BATCHED = [*HEADER, "Batch"]
BATCH = re.compile(r"[\w:.#-]{1,40}\Z")
KINDS = ("stuck", "decide", "review", "do")
RANK = {"stuck": 0, "decide": 1, "review": 1, "do": 2}
AGED = timedelta(days=1)  # an item waiting this long under a priority line goes first, so none starves
CELL = re.compile(r"(?<!\\)\|")
WORD = re.compile(r"[^\W\d_]{3}")  # turn_block.py's rule for a need's name


class QueueError(ValueError):
    """A queue edit or read that can't go as asked; str(error) says why."""


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    name: str
    source: str
    since: str
    batch: str = ""
    band: int = 0  # read()'s priority band: 0 aged under it, 1 its own, 2 the rest; a card stays in one

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
    if len(rows) < 2 or _cells(lines[rows[0]]) not in (HEADER, BATCHED):
        raise QueueError(f"the Queue table's header isn't {_row(HEADER)} or {_row(BATCHED)}: fix it by hand")
    return rows[2:]


def _item(row: str, width: int = len(HEADER)) -> Item:
    cells = _cells(row)
    if len(cells) != width or not cells[0].isdigit() or cells[1] not in KINDS:
        raise QueueError(f"a Queue row it can't read: {row.strip()!r}: fix it by hand")
    return Item(int(cells[0]), *cells[1:5], cells[5] if width > len(HEADER) else "")


def _columns(lines: list[str], start: int, end: int) -> None:
    """Writes the Batch column into a table from before it, each old row's cell empty.
    Raises QueueError on a table it can't read, which it leaves as it is."""
    rows = _table(lines, start, end)
    width = _width(lines, start, end)
    for i in rows:
        _item(lines[i], width)
    if width == len(HEADER):
        table = [i for i in range(start + 1, end) if lines[i].startswith("|")]
        lines[table[0]], lines[table[1]] = _row(BATCHED), "|" + "---|" * len(BATCHED)
        for i in table[2:]:
            lines[i] = lines[i].rstrip() + "  |"


def _width(lines: list[str], start: int, end: int) -> int:
    return len(_cells(next(lines[i] for i in range(start + 1, end) if lines[i].startswith("|"))))


def read(lines: list[str], ahead: Callable[[Item], bool] | None = None,
         now: datetime | None = None, held_since: datetime | None = None) -> list[Item] | None:
    """The open items in the order the user gets them, or None when project.md has no
    Queue section yet. ahead, the user's priority line, set at held_since, puts first each
    item that has waited AGED or more under it, longest-waiting first, then the items it
    matches, then the rest, those two in the usual order. Raises QueueError on a table it
    can't read."""
    bounds = _bounds(lines)
    if bounds is None:
        return None
    rows = _table(lines, *bounds)
    width = _width(lines, *bounds)
    items = sorted((_item(lines[i], width) for i in rows), key=lambda item: (RANK[item.kind], item.id))
    if ahead is None:
        return items
    old = (now or datetime.now()) - AGED
    aged = lambda item: max(_since(item), held_since or datetime.min) <= old
    banded = [replace(item, band=0 if aged(item) else 1 if ahead(item) else 2) for item in items]
    # The aged go longest-waiting first, past kind, so a run of reviews can't hold a Do back.
    return sorted(banded, key=lambda item: (0, max(_since(item), held_since or datetime.min), _since(item), item.id)
                  if item.band == 0 else (item.band,))


def _since(item: Item) -> datetime:
    try:
        return datetime.strptime(item.since, "%Y-%m-%d %H:%M")
    except ValueError:  # a hand-edited time: never aged
        return datetime.max


def _one_line(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value.strip() or "\r" in value:
        raise QueueError(f"{name} takes one non-empty line")
    return value.strip()


def create(lines: list[str]) -> None:
    """Writes an empty Queue section before Decisions, or at the end, unless there is one."""
    if _bounds(lines) is None:
        at = lines.index("## Decisions") if "## Decisions" in lines else len(lines)
        lines[at:at] = [HEADING, "", f"{COUNTER}1", "", _row(HEADER), "|" + "---|" * len(HEADER), ""]


def add(lines: list[str], kind: str, name: str, source: str, now: datetime | None = None, batch: str = "") -> Item:
    """Adds an item under the table and returns it, writing the Batch column the first time a
    batch is given. A project from before the queue has no section: `create` writes it, and
    only `project.py queue import` calls that, so the calls its last reply named arrive with
    the queue."""
    if kind not in KINDS:
        raise QueueError(f"kind {kind!r} isn't one of: {', '.join(KINDS)}")
    name, source = _one_line("the name", name), _one_line("--from", source)
    if len(name) > 80 or not WORD.search(name):
        raise QueueError("the name is 1-80 characters with a word of 3+ letters, as a turn-block need's is")
    if batch and not BATCH.match(batch):
        raise QueueError("--batch takes one word of up to 40 characters, such as post or merge:receipts")
    if _bounds(lines) is None:
        raise QueueError("this project has no Queue yet: start it with `queue import`, which queues every item your "
                         "last reply named")
    start, end = _bounds(lines)
    rows = _table(lines, start, end)
    if batch:
        _columns(lines, start, end)
    width = _width(lines, start, end)
    counter = next((i for i in range(start + 1, end) if lines[i].startswith(COUNTER)), None)
    if counter is None:
        raise QueueError(f"the Queue section has no `{COUNTER}<n>` line: fix it by hand")
    stored = lines[counter][len(COUNTER):].strip()
    # The counter, unless a hand edit left a row at or past it.
    ident = max([int(stored) if stored.isdigit() else 1, *(_item(lines[i], width).id + 1 for i in rows)])
    item = Item(ident, kind, name, source, (now or datetime.now()).strftime("%Y-%m-%d %H:%M"), batch)
    last = rows[-1] if rows else [i for i in range(start + 1, end) if lines[i].startswith("|")][1]
    cells = [str(item.id), item.kind, item.name, item.source, item.since, *([batch] if width > len(HEADER) else [])]
    lines.insert(last + 1, _row(cells))
    lines[counter] = f"{COUNTER}{ident + 1}"
    return item


def batch(lines: list[str], key: str, idents: list[int]) -> list[Item]:
    """Puts open items in batch key, writing the column if it's new, and returns them: a
    call queued before its batch was known, such as one from `queue import`, keeps its id."""
    if not BATCH.match(key):
        raise QueueError("--batch takes one word of up to 40 characters, such as post or merge:receipts")
    bounds = _bounds(lines)
    if bounds is None:
        raise QueueError("project.md has no Queue section")
    _columns(lines, *bounds)
    width, found = len(BATCHED), []
    for i in _table(lines, *bounds):
        item = _item(lines[i], width)
        if item.id in idents:
            found.append(replace(item, batch=key))
            lines[i] = _row([str(item.id), item.kind, item.name, item.source, item.since, key])
    if missing := sorted(set(idents) - {item.id for item in found}):
        raise QueueError(f"no open Queue item {', '.join(map(str, missing))}")
    return found


def done(lines: list[str], ident: int) -> Item:
    """Removes the item with this id and returns it."""
    bounds = _bounds(lines)
    if bounds is None:
        raise QueueError("project.md has no Queue section")
    for i in _table(lines, *bounds):
        item = _item(lines[i], _width(lines, *bounds))
        if item.id == ident:
            del lines[i]
            return item
    raise QueueError(f"no open Queue item {ident}")


def shown(text: str) -> str:
    """text as a reply writes it, so it renders as typed: an `&` that starts a character
    reference as `&amp;`, and each `<` that opens raw HTML merge-gate's pick reader refuses,
    as turn_block reads it (UNSAFE, or a `<details` fold), as `&lt;`, which keeps the reply's
    picks; a link, a lone `<`, or a lone `&` stays as typed."""
    text = re.sub(r"&(?=#?\w+;)", "&amp;", text)
    for pattern in (turn_block.UNSAFE, turn_block.OPENS_FOLD):
        text = pattern.sub(lambda match: "&lt;" + match.group()[1:], text)
    return text


def card(items: list[Item]) -> list[Item]:
    """The items the next card shows: the top one, and each other of its batch in its
    priority band, so a card never carries an item past one the priority puts first."""
    top = items[0]
    return [top, *(item for item in items[1:] if top.batch and item.batch == top.batch and item.band == top.band)]


def strip(items: list[Item]) -> str:
    """The line a reply carries while the queue holds items: which it shows of how many,
    and the name and asker of the one, or the batch and each name of a card that shows
    several, each by its id, the number its need and the card give it."""
    shows = card(items)
    if len(shows) > 1:
        names = "; ".join(f"{item.id} {shown(item.name)}" for item in shows)
        return f"{len(shows)} of {len(items)} need you, on one card · {shown(shows[0].batch)} · {names}"
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
    shows = card(items)
    listed = [f"  {item.id} {item.kind} · {item.name} · {item.source} · since {item.since}"
              + (f" · {item.batch}" if item.batch else "") for item in items]
    return "\n".join([strip(items), f"needs: [{','.join(as_json(item.need()) for item in shows)}]", "queue:", *listed])

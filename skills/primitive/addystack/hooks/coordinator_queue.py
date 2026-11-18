#!/usr/bin/env python3
"""Stop: in a ◆ coordinator thread, send a reply back once when it hides what the project's
queue holds for the user.

The user had to ask. In the 14 days to Nov 18, 2026 they typed "anything else waiting for
me?", "what's next?", or the like 17 times in ◆ threads on their two machines, 6 of them in
one afternoon. On one machine, 10 of the 16 replies just before kept open calls in the turn
block's `standing`, which the reply doesn't show and Prefrontal counts as not waiting: 9
with `needs` empty, and one card that showed a single call with 14 more behind it. None
said how many waited. Across all ◆ replies in those days, 11.5% and 10.1% on the two
machines parked a decide or review that way, against 2.3% and 0.9% in other threads. The
coordinator skill already said to show the top call on every reply; the text alone didn't
hold.

The queue is project.md's `## Queue` table (project_queue.py), which the coordinator
writes with `project.py queue`. A reply goes back, with each reason, when:

- its turn block names an item, in `needs` or `standing`, that the queue doesn't hold, or
  names it with another kind or name, so every call the thread puts to the user lives where
  the next wake and a compaction find it;
- the queue holds items and the top one isn't in `needs`, so Prefrontal and chief count the
  thread as waiting on that call;
- the queue holds items and no line the user sees, outside code, comments, and folds,
  carries the strip `<k> of <N> need you · <top item's name>` with N the queue's length, so
  the reply says what waits, and how much, without being asked.

The send-back names the top item, its need, and `queue done` for an answer the coordinator
hasn't recorded, since an answered call left on the queue would come back as its top. A
project with no Queue section yet also counts what the reply before this turn's prompt
named, so its open items reach the queue instead of dropping out of the next reply.

A coordinator is a thread whose T3 title holds `◆ <project>` (t3_child.coordinator_project),
and its project.md is `~/.local/state/orchestrate/<project>/project.md` whose `Coordinator:`
link names that thread. Doubt allows: outside T3, a session T3 doesn't know, another thread's
project.md, a Queue table it can't read, or a reply with no valid turn block, which
routine_stop.py sends back. `stop_hook_active` keeps it to one send per stop, as the other
Stop hooks do, so a reply after another hook sent the agent on isn't checked again.
Coordinators run on Claude (t3-delegation's Roles table), so it ships for Claude Code alone."""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_queue, t3_child, transcripts, turn_block  # noqa: E402

LINK = re.compile(r"t3-thread://v2/[^/>\s)]+/([^>\s)]+)")  # project.py's, for the Coordinator header
OPEN_FOLD = re.compile(r"<details\b", re.I)
CLOSE_FOLD = re.compile(r"</details\s*>", re.I)


def project_file(project, thread):
    """The project's project.md lines when its Coordinator header links this thread, else None."""
    path = Path.home() / ".local" / "state" / "orchestrate" / project / "project.md"
    try:
        lines = path.read_text().split("\n")
    except (OSError, UnicodeDecodeError):
        return None
    header = next((line for line in lines if line.startswith("Coordinator:")), "")
    found = LINK.search(header)
    return (path, lines) if found and found.group(1) == thread else None


def visible_lines(reply):
    """The reply's text the user sees without opening anything, a line at a time: outside
    code blocks, HTML comments (the turn block among them), and folds, nested ones too.
    A fold's summary line counts as folded."""
    lines = turn_block.lines_ended(reply).split("\n")
    shown, depth, comment = [], 0, False
    for line, fenced in zip(lines, turn_block.in_fence(lines)):
        if fenced:
            continue
        text = ""
        while line:
            mark = "-->" if comment else "<!--"
            at = line.find(mark)
            if not comment:
                text += line if at < 0 else line[:at]
            line = "" if at < 0 else line[at + len(mark):]
            comment = (not comment) if at >= 0 else comment
        opens, closes = len(OPEN_FOLD.findall(text)), len(CLOSE_FOLD.findall(text))
        if not depth and not opens and not closes:
            shown.append(text)
        depth = max(0, depth + opens - closes)
    return shown


def earlier_items(path):
    """The user items, needs and standing, that the reply before this turn's prompt named;
    () when there's none or it can't be read."""
    for exchange in reversed(transcripts.exchanges(path)):
        if exchange.reply:
            try:
                return turn_block.parse(exchange.reply).items
            except turn_block.Malformed:
                return ()
    return ()


def problems(turn, reply, items, earlier=()):
    """Why the reply hides the queue, one reason a line; [] when it shows it. With no Queue
    section yet (items None), what the reply before named counts as open too, so the first
    reply after the queue arrives can't drop it unqueued."""
    held = {item.id: item.need() for item in items or []}
    found = []
    if items is None:
        named = {item.id for item in turn.items}
        found += [f"the reply before named {item.kind} {item.id} \"{item.name}\", which the queue doesn't hold"
                  for item in earlier if item.id not in named]
    for item in turn.items:
        named = {"id": item.id, "kind": item.kind, "name": item.name}
        queued = held.get(item.id)
        if queued is None:
            found.append(f"its turn block names {item.kind} {item.id} \"{item.name}\", which the queue doesn't hold")
        elif named != queued:
            found.append(f"its turn block's item {item.id} is {item.kind} \"{item.name}\", but the queue's is "
                         f"{queued['kind']} \"{queued['name']}\"")
    if items:
        top = items[0]
        if top.id not in {need.id for need in turn.needs}:
            found.append(f"its `needs` leaves out the queue's top item, {top.id}")
        if not any(int(match.group(2)) == len(items) and top.name.casefold() in line.casefold()
                   for line in visible_lines(reply) for match in project_queue.STRIP.finditer(line)):
            found.append(f"no line the user sees carries the strip `{project_queue.strip(items)}`")
    return found


def feedback(project, path, items, found):
    where = "~/" + str(path.relative_to(Path.home()))
    script = "the coordinator skill's `scripts/project.py`"
    reasons = "; ".join(found)
    if not items:
        return (f"This ◆ {project} thread's reply hides what waits on the user: {reasons}. Every call or Do this "
                f"thread puts to the user goes on its queue first, in {where}: queue each one still open, in the order "
                f"it arose, with {script} `{path.parent} queue add <kind> \"<name>\" --from \"<worker> <thread link>\"`, "
                "and give its need the id that prints; leave out one the user already answered. Then send your whole "
                "reply again, ending on the queue's top item as `queue show` prints it; T3 shows only a turn's last "
                "message, so it has to stand on its own. Add no note about the change.")
    top = items[0]
    need = json.dumps(top.need(), ensure_ascii=False, separators=(",", ":"))
    return (f"This ◆ {project} thread's queue ({where}) holds {len(items)} item{'s' if len(items) > 1 else ''} for "
            f"the user, and your reply hides them: {reasons}. While the queue holds an item, every reply here, a ⏳ "
            "status or a quiet wake's included, ends on its top item (coordinator step 5): its card the first time, "
            f"then its question, the strip `{project_queue.strip(items)}`, and Next, with `{need}` in the turn "
            f"block's `needs`. If the user already answered it, record that first with {script} `{path.parent} queue "
            f"done {top.id} --answer \"<the pick> · the user: '<their words>'\"` and show the next one; `queue show` "
            "prints the strip and the need. Send your whole reply again; T3 shows only a turn's last message, so it has to stand on its own. "
            "Add no note about the change.")


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active") or not os.environ.get("T3CODE_CLI_PATH"):
        return
    found = t3_child.coordinator_project(event.get("session_id"))
    place = found and project_file(*found)
    if not place:
        return
    path, lines = place
    reply = event.get("last_assistant_message")
    try:
        items = project_queue.read(lines)
        turn = turn_block.parse(reply)
    except (project_queue.QueueError, turn_block.Malformed):
        return
    earlier = earlier_items(event.get("transcript_path")) if items is None else ()
    reasons = problems(turn, reply, items, earlier)
    if reasons:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop",
                                                 "additionalContext": feedback(found[0], path, items, reasons)}}))


if __name__ == "__main__":
    main()

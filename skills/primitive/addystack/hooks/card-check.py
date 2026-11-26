#!/usr/bin/env python3
"""Stop, in Claude Code: sends a reply back once when its turn block (turn_block.py) offers a
`stop:push` option that asks for a push (a push_go.STEPS verb) and says it dismisses an
approval, but isn't a go push-gate.py takes (push_go.literal_go), so the agent rewords it
before the user picks it.
A refused pick costs the user a pick, a denial, and a new card: on Nov 26, 2026 push-gate
refused three informed goes in a row on one push (PushGate in test_hooks.py replays them).

It checks only what the reply can know offline. Whether a push dismisses an approval
depends on reviews the reply can't see, so an option that names no dismissal passes, and so
does one whose PRs the gate would find incomplete. An option whose every push verb is
declined (DECLINES), such as "don't push #12, it dismisses the approval", passes; one with a
condition, a modal, or a `no:` lead asks for a push the gate refuses, so it goes back. A `stop:merge` option isn't checked: merge-gate reads the go only
for a PR with no checks, which the reply can't see either.

Of 1,198 cards with a push or merge stop from Nov 18 to 26, 2026, on two machines, it flags
21 push options, 16 distinct. T3 shows a reply as it streams, so the user sees the first card too;
the resent one comes seconds later and is the one a key answers (user_turn.answered).
stop_hook_active keeps it to one send per stop, and any doubt or error passes.

It also sends back a reply whose block is `running` when nothing in T3 will wake its thread
on what it waits for (wake_gap). A user's Stop ends every PR watch on a thread without a
word (T3 0.1.13's holdStoppedThread), and on Nov 26, 2026 a coordinator promised CI news on
#6153 from such a watch for three hours, until the user asked "WHY DO I KEEP HAVING TO ASK
FOR STATUS?". So it goes back when it names an open PR this thread watched and never
unwatched that T3 no longer watches; when its coordinator's Workers table says a worker runs
on another machine, whose end wakes nothing here, and no timer or task is pending; when no
PR is watched, no task or child is pending, and no timer on the thread runs next; and when
its `eta` has no timer by then or pending task, since a watch can miss a re-run that ends
between polls. Replayed on 2,284 `running` turns from Nov 19 to 26, 2026, on two machines,
it sends back the turn before 10 of the 12 status asks that a missing wake caused. It reads
T3's state database, since `t3 thread show` lists no pending task while a run is active,
and passes outside T3 or when the database can't be read."""
import json, os, pathlib, re, sys, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DISMISS = re.compile(r"\bdismiss", re.I)
DECLINES = r"\b(?:don't|dont|do not|never|not|without|skip|hold|avoid)\s+(?:\w+\s+)?"  # then a push verb
SHAPE = ("the push first, naming each PR, then the dismissal, as in \"push #12 and #13 (dismisses the reviewer's "
         "approval)\" or \"push the stack (dismisses the reviewer's approvals on #12 and #13)\", then only steps such as "
         "\"post the reply\", with no other step before the push, and no condition, modal, or `no:` lead, which push-gate "
         "takes as the user's go")


def refused(turn):
    """Each option of turn that asks for a push dismissing an approval that push-gate wouldn't take."""
    import push_go
    declines = re.compile(rf"{DECLINES}{push_go.VERB}\b", re.I)
    text = lambda option: option.text.replace("’", "'")  # as push_go.read reads it
    return [option for option in turn.options if option.cls == "stop:push" and DISMISS.search(option.text)
            and push_go.STEPS.search(declines.sub("", text(option)))
            and not push_go.literal_go(option.text)]


# T3's work that outlives the run and wakes the thread when it ends (pendingBackgroundTurnItems).
ACTIVE = "('pending', 'running', 'waiting')"
UNITS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600, "hour": 3600}
DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b", re.I)


def seconds(eta):
    """The eta's duration in seconds, such as "about 6 min" or "1 h 30 min", or None for a
    clock time, a range's words, or anything else it can't read."""
    found = DURATION.findall(eta or "")
    if not found or re.search(r"\d:\d", eta):
        return None
    unit = lambda word: UNITS.get(word.lower().rstrip("s"), UNITS.get(word.lower(), 60))
    return sum(float(number) * unit(word) for number, word in found)


def when(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def wakes(thread):
    """What T3 holds for thread, from its state database: (watched PR numbers, the open PRs
    whose watch this thread started and never ended, which T3 then ended, pending task kinds,
    the next timer's epoch or None). Raises sqlite3.Error or LookupError in doubt."""
    import t3_child
    db = t3_child.connect()
    try:
        row = db.execute("select payload_json, active_provider_thread_id from orchestration_v2_projection_threads "
                         "where thread_id = ? and deleted_at is null", (thread,)).fetchone()
        if row is None:
            raise LookupError(thread)
        links = json.loads(row[0]).get("pullRequests") or []
        # A stack-dismissed link's watch wakes nobody (T3's pullRequestWatchTasks).
        watched = {link.get("number") for link in links if link.get("watch") and link.get("source") != "stack-dismissed"}
        calls = {}  # each PR's last watch or unwatch call that went through
        for name, given, output in db.execute(
                "select json_extract(payload_json, '$.toolName'), json_extract(payload_json, '$.input'), "
                "json_extract(payload_json, '$.output') from orchestration_v2_projection_turn_items where thread_id = ? "
                "and type = 'dynamic_tool' and status = 'completed' and json_extract(payload_json, '$.toolName') "
                "like '%watch_pull_request' order by ordinal", (thread,)):
            given = json.loads(given) if given else {}
            number = given.get("number") or (re.search(r"/pull/(\d+)", str(given.get("url"))) or [None, None])[1]
            if number and not re.search(r'"isError": ?true|hook error', str(output)):
                calls[int(number)] = not name.endswith("unwatch_pull_request")
        ended = {link.get("number") for link in links if calls.get(link.get("number")) and not link.get("watch")
                 and (link.get("snapshot") or {}).get("state") == "open"}
        tasks = [task.get("kind") for payload, in db.execute(
            "select payload_json from orchestration_v2_projection_provider_threads where thread_id = ?1 "
            "and (?2 is null or provider_thread_id = ?2)", (thread, row[1]))
            for task in json.loads(payload).get("pendingBackgroundTasks") or []]
        tasks += [kind for kind, persistent in db.execute(
            "select i.type, json_extract(i.payload_json, '$.input.persistent') from orchestration_v2_projection_turn_items i "
            "left join orchestration_v2_projection_runs r on r.run_id = i.run_id "
            f"where i.thread_id = ? and i.type in ('command_execution', 'dynamic_tool', 'subagent') and i.status in {ACTIVE} "
            "and (r.status is null or r.status != 'rolled_back')", (thread,)) if persistent != 1]
        timer = db.execute("select min(next_run_at) from scheduled_tasks where thread_id = ? and enabled = 1 "
                           "and thread_mode = 'continue' and next_run_at is not null", (thread,)).fetchone()[0]
    finally:
        db.close()
    return watched, ended, tasks, when(timer) if timer else None


LINK = re.compile(r"t3-thread://v2/([^/>\s)]+)/([^>\s)]+)")  # as project.py reads a coordinator's links
# A bare thread id, as `project.py worker --thread mcp:launch:…` writes one: a launched thread,
# a delegated child, or a UUID.
BARE = re.compile(r"(?<![\w:/])(mcp:launch:[0-9a-f]+|thread:[\w%:.-]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
CELL = re.compile(r"(?<!\\)\|")  # project.py's: a cell ends at a | that isn't escaped


def remote(cell, coordinator, known):
    """Whether a Workers row's Thread cell names a thread on another machine: a link to
    another environment than the coordinator's, or a bare id that T3 here doesn't know."""
    link = LINK.search(cell)
    if link:
        return link.group(1) != coordinator
    bare = BARE.search(cell)
    return bool(bare) and not known(bare.group(1))


def remote_workers(thread, known):
    """The live Workers rows (running, overdue, or unknown), in project.md of the coordinator
    project whose thread this is, whose thread is on another machine: T3 here can't see such
    a thread end, so nothing here wakes on it. known(id) says whether T3 here has a thread."""
    found = []
    for path in pathlib.Path(os.environ.get("ADDYSTACK_ORCHESTRATE", "~/.local/state/orchestrate")).expanduser().glob(
            "*/project.md"):
        lines = path.read_text().splitlines()
        head = next((LINK.search(line) for line in lines if line.startswith("Coordinator:")), None)
        if not head or head.group(2) != thread:
            continue
        start = next((at for at, line in enumerate(lines) if line.strip() == "## Workers"), len(lines))
        stop = next((at for at in range(start + 1, len(lines)) if lines[at].startswith("## ")), len(lines))
        rows = [[cell.strip() for cell in CELL.split(line.strip().strip("|"))] for line in lines[start:stop]
                if line.startswith("|")]
        for cells in rows[2:]:
            row = dict(zip(rows[0], cells))
            if re.match(r"(running|overdue|unknown)\b", row.get("State", "")) and remote(
                    row.get("Thread", ""), head.group(1), known):
                found.append(row.get("Worker", "?"))
    return found


def known_thread(thread):
    import t3_child
    db = t3_child.connect()
    try:
        return db.execute("select 1 from orchestration_v2_projection_threads where thread_id = ?", (thread,)).fetchone() is not None
    finally:
        db.close()


def wake_gap(turn, reply, thread, now):
    """Why a `running` turn's thread has nothing to wake it on what it waits for, or None
    when it has, the turn isn't running, or an eta it can't read leaves only a watch."""
    if turn.state != "running":
        return None
    watched, ended, tasks, timer = wakes(thread)
    named = {int(number) for number in re.findall(r"(?<![\w/])#(\d+)\b", reply[:reply.rfind("<!--")])}
    if named & ended:
        prs = ", ".join(f"#{number}" for number in sorted(named & ended))
        return (f"this reply names {prs}, which this thread watched and never unwatched, but T3 no longer watches "
                "it: a user's Stop ends every watch on a thread without a word. Call `watch_pull_request` on it again "
                "before ending the turn")
    if not (tasks or timer) and (away := remote_workers(thread, known_thread)):
        return (f"this reply's turn block is `running`, and Workers says {', '.join(away)} runs on another machine, "
                "whose end wakes nothing here. Set a `once` `schedule_task` on this thread at the time you expect "
                "its news, or read its status now")
    if not (watched or tasks or timer):
        return ("this reply's turn block is `running`, but nothing in T3 will wake this thread: no PR here is "
                "watched (`watch_pull_request` returns `wasWatching: false` for one T3 ended), no background "
                "task or child is pending, and no timer on this thread runs next. Set up the wake the reply waits "
                "on before ending the turn: watch each PR it waits on, or set a `once` `schedule_task` on this "
                "thread at the time it expects news. If nothing is pending, end `stop` or `done`")
    due = seconds(turn.eta)
    if due is None or tasks or timer is not None and timer <= now + due + max(600, due / 2):
        return None
    return (f"this reply's eta is {turn.eta}, but only a PR watch will wake this thread, and a watch can miss a "
            "re-run that ends between its polls. Set a `once` `schedule_task` on this thread at the eta, or drop "
            "the eta if it isn't measured")


def main():
    try:
        event = json.loads(sys.stdin.read())
        if event.get("stop_hook_active"):
            return
        import turn_block
        turn = turn_block.parse(event.get("last_assistant_message") or "")
        found = refused(turn)
    except Exception:  # Malformed included: no block, nothing to check
        return
    try:
        import t3_child
        gap = wake_gap(turn, event["last_assistant_message"], os.environ.get("T3CODE_THREAD_ID", ""), time.time()) \
            if t3_child.in_t3() else None
    except Exception:  # T3's database unread: a T3 outage never holds a turn
        gap = None
    # A running block carries no options (turn_block.parse), so at most one of these holds.
    if gap:
        reason, step = gap[0].upper() + gap[1:], "with the wake set"
    elif found:
        reason = "; ".join(f'option {option.key}, "{option.text}", is stop:push, but push-gate would refuse it if the '
                           f"user picked it" for option in found) + f". Write it as {SHAPE}"
        step = "with only that option reworded, or its other steps split into their own option"
    else:
        return
    # Claude Code continues a Stop through additionalContext, shown as "Stop hook feedback";
    # its docs keep "block" for errors.
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
        f"{reason}. Send your whole reply again {step}. T3 shows the turn's last message as its reply, so the "
        "resent reply has to stand on its own. Add no note about the change.")}}))

main()

#!/usr/bin/env python3
"""chief's inbox: from what the router thread read with T3's tools on each machine, the
project.md digests, and Oliver's open PRs on GitHub, one ranked card of what waits on
Oliver, with flags for what no other view shows. It reads files, GitHub, and chief's
Executor app, and writes only its own state folder and chief's app. The one thing it
passes on to Oliver's threads is his own answer, word for word (D10), and the router
sends it.

  inbox.py list                 the t3_thread_list calls still to make, as JSON lines of
                                their arguments; with none left, writes threads.json
  inbox.py plan                 the t3_thread_read calls still to make, the same way
  inbox.py card [--no-gh] [--no-record]   merge this turn's reads into the cache, record
                                           the run in Executor, print the card
  inbox.py relay                plan the sends for Oliver's pending answers, as JSON lines
  inbox.py mark ID sent|failed [DETAIL]    after a send, mark the answer in Executor
  inbox.py answer "<item>: <answer>"       record an answer Oliver typed in the chief thread;
                                           "<item>: snooze <when>" and "<item>: unsnooze" snooze it
  inbox.py live < threads.json  the calls one machine's threads make, for the live feeder
                                (chief/feeder), as record_live's items

list, plan and card take T3's tool results from the router's own transcript
(tool_results.py), never from text an agent copied.

Files in the state folder (CHIEF_STATE, default ~/.local/state/chief):
  threads.json     every unsettled main thread each reachable machine listed
  notes.json       the machines that didn't answer, for the card's fold
  mac-projects.json  the Mac feed's newest projects.py output
  cache.json       each thread's read, kept while its updatedAt holds

A thread whose updatedAt hasn't moved since its last read has the same messages, so it
is read again only when it changes: the first run reads every idle thread, later runs a
handful. The rules port Prefrontal's lanes (olivercederborg/prefrontal,
Sources/PrefrontalKit/Lanes.swift and NeedsYouGroups.swift) where they overlap, so the
two agree on what waits on Oliver."""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projects as project_files  # noqa: E402
import snooze  # noqa: E402
import tool_results  # noqa: E402
import turn_block  # noqa: E402  (hooks/turn_block.py, linked in)

STATE = os.environ.get("CHIEF_STATE", "~/.local/state/chief")
ORCHESTRATE = os.environ.get("CHIEF_ORCHESTRATE", "~/.local/state/orchestrate")
# chief-app's shell caller for the Executor app `chief` (github.com/olivercederborg/chief-app).
CHIEF_BIN = os.environ.get("CHIEF_BIN", "~/Developer/personal/chief-app/bin/chief")
MACHINES = {"8ef1f244-6d9b-47af-addf-af15ee5f56ee": "devbox", "0c5f5b0f-2c19-43e6-8a82-8fe66c1580b9": "Mac"}
# chief's own threads: the router and the Mac feed. They never wait on Oliver.
OWN_TITLES = ("chief", "chief · Mac feed")
# Run statuses T3 counts as at work; `waiting` is a run draining after its last turn.
ACTIVE = {"queued", "preparing", "starting", "running", "waiting"}
# How far from the end a tail read starts: the last reply, its checkpoint, and the
# message before it sit within the thread's last few timeline items.
TAIL = 12
# Tail reads per run. The first run on a machine with 70 idle threads would read ~0.5 MB;
# the rest wait for later runs, and the card counts them as not read yet.
TAILS = 25
# A worker's reply its coordinator hasn't taken in counts once it has sat this long, as
# Prefrontal's childQuestionLimit.
UNREAD_AFTER = timedelta(minutes=10)
# A running block with no ETA that is a time counts as never re-woken after an hour: of
# 2,231 running replies in T3 to Nov 4, 2026, 99% woke within 60 minutes.
IDLE_LIMIT = timedelta(hours=1)
DAY = timedelta(hours=24)
NOTES = 3
NEEDS = 5
SPAN = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?|s|secs?|seconds?)\b", re.I)
LINK = re.compile(r"t3-thread://v2/([^/>\s]+)/([^>\s·]+)")


# ---------------------------------------------------------------- inputs

def state_dir() -> Path:
    path = Path(STATE).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def when(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def key(env: str, thread: str) -> str:
    return f"{env}/{thread}"


def link(env: str, thread: str) -> str:
    return f"t3-thread://v2/{env}/{thread}"


def link_key(text) -> str | None:
    found = LINK.search(text or "")
    return key(found.group(1), found.group(2)) if found else None


# ---------------------------------------------------------------- plan

def plan(threads, cache):
    """The reads a run needs: a tail read of each idle thread whose updatedAt moved since
    its cached read, newest first and at most TAILS of them; a status read of each thread
    at work, every run, since an approval or question can wait on Oliver mid-run; and a
    first-message read of each agent-made thread never read, which says whether it's a
    coordinator's worker."""
    reads, tails = [], 0
    for thread in sorted(threads, key=lambda item: item.get("updatedAt") or "", reverse=True):
        if thread.get("title") in OWN_TITLES or thread.get("snoozed"):
            continue
        cached = cache.get(key(thread["env"], thread["id"]), {})
        # A turn cached before options were kept is read again once, for the page's buttons.
        stale = cached.get("updatedAt") != thread.get("updatedAt") or "options" not in (cached.get("turn") or {"options": 0})
        tail = thread.get("status") not in ACTIVE and stale and tails < TAILS
        tails += tail
        status = thread.get("status") in ACTIVE
        first = thread.get("createdBy") == "agent" and "workerOf" not in cached
        if not (tail or status or first):
            continue
        read = {"environmentId": thread["env"], "threadId": thread["id"], "updatedAt": thread.get("updatedAt")}
        if tail:
            read["tail"] = {"view": "messages", "afterPosition": max(0, int(thread.get("itemCount") or 0) - TAIL),
                            "limit": TAIL, "maxCharsPerItem": 6000, "runLimit": 1}
        if status:
            read["status"] = {"view": "messages", "limit": 1, "maxCharsPerItem": 1, "runLimit": 1}
        if first:
            read["first"] = {"view": "messages", "limit": 1, "maxCharsPerItem": 600, "runLimit": 1}
        reads.append(read)
    return reads


def merge(cache, reads):
    """This turn's reads (gather) into the cache. A tail read replaces the thread's reply facts and
    stamps its updatedAt; a status read records the requests open mid-run; a first read
    sets workerOf, which never changes."""
    for read in reads:
        entry = cache.setdefault(key(read["env"], read["id"]), {})
        if "workerOf" in read:
            entry["workerOf"] = link_key(read["workerOf"]) if read["workerOf"] else None
        if "turn" in read:
            for name in ("replyAt", "headline", "lastUserAt", "pending", "runCompletedAt"):
                entry[name] = read.get(name)
            entry["turn"] = turn_of(read.get("turn"))
            entry["updatedAt"] = read.get("updatedAt")
        if "activePending" in read:
            entry["activePending"] = read["activePending"]
            entry["activeAt"] = read.get("updatedAt")
    return cache


def turn_of(block):
    """The reply's turn block, as the router copied it from the reply's last line, read by
    hooks/turn_block.py, the checker every reply passes: a dict, or None when the reply
    has no block or a malformed one."""
    if not isinstance(block, str) or not block.strip():
        return None
    try:
        turn = turn_block.parse(block.strip())
    except turn_block.Malformed:
        return None
    return {"state": turn.state, "needs": [{"id": need.id, "kind": need.kind, "name": need.name} for need in turn.needs],
            "options": [{"key": option.key, "class": option.cls, "text": option.text} for option in turn.options],
            "eta": turn.eta, "project": turn.project}


# ---------------------------------------------------------------- T3 results
# What the router's T3 calls returned this turn, as tool_results.py reads them from its
# transcript. Each command prints the calls still to make as their arguments, so the
# router only makes calls and never copies a result.

LIST_ARGS = {"allProjects": True, "settled": False, "includeSubagents": False, "limit": 100}
# A continued read takes the rest of a cut reply in one go; a reply is rarely past 50k.
REST = 50000
FEED_TITLE = "chief · Mac feed"
JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def canon(args) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def answered(calls, tool):
    """Each call of one tool by its arguments, the latest winning."""
    return {canon(call.args): call for call in calls if call.tool == tool}


def listing(calls):
    """(threads, notes, calls still to make) from this turn's t3_environment_links and
    t3_thread_list results: every page of this machine and each reachable linked machine,
    each thread once. A machine that isn't reachable, or whose list call failed, gets a
    note and no rows."""
    links = [call for call in calls if call.tool == "t3_environment_links"]
    if not links:
        raise ChiefError("call t3_environment_links first, then run this again")
    if links[-1].error:
        raise ChiefError(f"t3_environment_links failed: {links[-1].error}")
    here = links[-1].result.get("environmentId")
    machines, notes = [(here, "this machine")], []
    for linked in links[-1].result.get("links") or []:
        name = MACHINES.get(linked.get("environmentId")) or linked.get("label") or linked.get("environmentId")
        if linked.get("status") == "reachable":
            machines.append((linked["environmentId"], name))
        else:
            notes.append(f"{name} didn't answer: its link is {linked.get('status')}.")
    pages = {}
    for call in calls:
        if call.tool != "t3_thread_list" or any(call.args.get(name) != value for name, value in LIST_ARGS.items()
                                                if name != "limit"):
            continue
        pages[(call.args.get("environmentId") or here, int(call.args.get("cursor") or 0))] = call
    threads, missing = {}, []
    for env, name in machines:
        cursor, rows = 0, {}
        while True:
            page = pages.get((env, cursor))
            if page is None:
                missing.append(dict({"environmentId": env, **LIST_ARGS}, **({"cursor": cursor} if cursor else {})))
                break
            if page.error:
                notes.append(f"{MACHINES.get(env, name)} didn't answer: {cut(page.error, 100)}")
                break
            for item in page.result.get("threads") or []:
                row = thread_row(item, env)
                rows[key(row["env"], row["id"])] = row
            cursor = page.result.get("nextCursor")
            if not cursor:
                threads.update(rows)
                break
    return list(threads.values()), notes, missing


def thread_row(item, env):
    """threads.json's object for one t3_thread_list thread: its open PRs only."""
    found = LINK.search(item.get("link") or "")
    return {"env": found.group(1) if found else env, "id": item["threadId"], "title": item.get("title"),
            "status": item.get("status"), "createdBy": item.get("createdBy"), "updatedAt": item.get("updatedAt"),
            "itemCount": item.get("itemCount"), "snoozed": bool(item.get("snoozed")),
            "prs": [{"repo": pr.get("repository"), "number": pr.get("number"), "state": pr.get("state")}
                    for pr in item.get("pullRequests") or [] if pr.get("state") == "open"]}


def read_calls(read):
    """A planned read as its t3_thread_read calls: (kind, arguments) for each of tail,
    status and first it names."""
    return [(kind, {"environmentId": read["environmentId"], "threadId": read["threadId"], **read[kind]})
            for kind in ("tail", "status", "first") if kind in read]


def rest_call(env, thread, item_id, offset):
    return {"environmentId": env, "threadId": thread, "itemId": item_id, "textOffset": offset,
            "maxCharsPerItem": REST, "runLimit": 1}


def reply_text(reply, env, thread, results):
    """(the reply's whole text, the call still needed to finish it or None)."""
    text = reply.get("text") or ""
    offset = reply.get("nextTextOffset") if reply.get("textTruncated") else None
    while offset:
        args = rest_call(env, thread, reply.get("itemId"), offset)
        call = results.get(canon(args))
        if call is None:
            return text, args
        if call.error:
            return text, None
        part = next((item for item in call.result.get("items") or [] if item.get("itemId") == reply.get("itemId")), {})
        text += part.get("text") or ""
        offset = part.get("nextTextOffset") if part.get("textTruncated") and part.get("text") else None
    return text, None


def tail_facts(result, env, thread, results):
    """A read's tail fields from one tail read, or the call that would finish its cut
    reply. `turn` is the last reply's final line when it's a turn block, verbatim."""
    items = sorted(result.get("items") or [], key=lambda item: item.get("position") or 0)
    replies = [item for item in items if item.get("type") == "assistant_message"]
    reply = replies[-1] if replies else None
    text, needed = reply_text(reply, env, thread, results) if reply else ("", None)
    if needed:
        return None, needed
    after = reply.get("position", -1) if reply else -1
    users = [item.get("updatedAt") for item in items if item.get("type") == "user_message" and item.get("position", 0) > after]
    runs = result.get("recentRuns") or [{}]
    return {**reply_facts(text),
            "replyAt": reply.get("updatedAt") if reply else None,
            "lastUserAt": max(users) if users else None,
            "pending": int((result.get("thread") or {}).get("pendingRequestCount") or 0),
            "runCompletedAt": runs[0].get("completedAt")}, None


def reply_facts(text):
    """A reply's turn block, its final line verbatim when it is one, and its headline."""
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    return {"turn": last if last.startswith("<!-- turn") else None,
            "headline": lines[0].strip()[:100] if lines else ""}


def worker_of(result):
    """The `t3-thread://` link on the first user message's `Worker of:` line, else None."""
    items = result.get("items") or []
    first = items[0] if items and items[0].get("type") == "user_message" else {}
    return worker_line(first.get("text"))


def worker_line(text):
    found = re.search(r"^Worker of: (t3-thread://\S+)", text or "", re.M)
    return found.group(1) if found else None


def gather(planned, calls):
    """(reads, calls still to make, failed) for the planned reads: merge's objects for
    each thread whose reads all came back, the planned or continuing calls with no
    result yet, and the error of each read that failed. A failed read isn't retried; its
    thread keeps its cached read."""
    results = answered(calls, "t3_thread_read")
    reads, missing, failed = [], [], []
    for read in planned:
        found = {"env": read["environmentId"], "id": read["threadId"], "updatedAt": read.get("updatedAt")}
        whole = True
        for kind, args in read_calls(read):
            call = results.get(canon(args))
            if call is None:
                missing.append(args)
                whole = False
            elif call.error:
                failed.append(call.error)
                whole = False
            elif kind == "tail":
                facts, needed = tail_facts(call.result, read["environmentId"], read["threadId"], results)
                if needed:
                    missing.append(needed)
                    whole = False
                else:
                    found.update(facts)
            elif kind == "status":
                found["activePending"] = int((call.result.get("thread") or {}).get("pendingRequestCount") or 0)
            else:
                found["workerOf"] = worker_of(call.result)
        if whole:
            reads.append(found)
    return reads, missing, failed


def feed_projects(calls):
    """The Mac feed's newest projects.py output: the JSON block in the last reply of this
    turn's latest t3_thread_read of the feed thread, else None."""
    for call in reversed(calls):
        if call.tool != "t3_thread_read" or call.error:
            continue
        if (call.result.get("thread") or {}).get("title") != FEED_TITLE:
            continue
        replies = [item for item in call.result.get("items") or [] if item.get("type") == "assistant_message"]
        if not replies or replies[-1].get("textTruncated"):
            return None
        found = JSON_BLOCK.search(replies[-1].get("text") or "")
        try:
            digest = json.loads(found.group(1)) if found else None
        except ValueError:
            return None
        return digest if isinstance(digest, dict) and isinstance(digest.get("projects"), list) else None
    return None


def count(number, noun):
    return f"{number} {noun}{'' if number == 1 else 's'}"


def keeps(number):
    return "its thread keeps its last read" if number == 1 else "their threads keep their last read"


def turn_calls():
    return tool_results.turn_calls(tool_results.transcript_path())


# ---------------------------------------------------------------- facts

@dataclass
class Thread:
    env: str
    id: str
    title: str
    status: str
    updated: datetime | None
    prs: list
    turn: dict | None = None
    headline: str = ""
    reply_at: datetime | None = None
    last_user_at: datetime | None = None
    pending: int = 0
    run_completed: datetime | None = None
    worker_of: str | None = None
    read: bool = False

    @property
    def key(self):
        return key(self.env, self.id)

    @property
    def link(self):
        return link(self.env, self.id)

    @property
    def machine(self):
        return MACHINES.get(self.env, self.env[:8])

    @property
    def active(self):
        return self.status in ACTIVE

    @property
    def coordinator(self):
        return self.title.startswith("◆")

    @property
    def child(self):
        """A delegated task or subagent with no Worker of line reports to the agent that
        started it, not to Oliver."""
        return self.id.startswith("thread:") and not self.worker_of

    @property
    def state(self):
        return (self.turn or {}).get("state")

    @property
    def needs(self):
        return (self.turn or {}).get("needs") or []

    @property
    def ended(self):
        """When its last run ended, or its last reply when the run time is unknown."""
        return self.run_completed or self.reply_at or self.updated


def threads_from(listed, cache):
    found = []
    for item in listed:
        if item.get("title") in OWN_TITLES or item.get("snoozed"):
            continue
        entry = cache.get(key(item["env"], item["id"]), {})
        fresh = entry.get("updatedAt") == item.get("updatedAt")
        thread = Thread(env=item["env"], id=item["id"], title=item.get("title") or "Untitled",
                        status=item.get("status") or "",
                        updated=when(item.get("updatedAt")), prs=item.get("prs") or [],
                        worker_of=entry.get("workerOf"))
        if entry and "turn" in entry:
            # A stale read still says who asked what; a fresh one is the thread as it is.
            thread.turn = entry.get("turn")
            thread.headline = entry.get("headline") or ""
            thread.reply_at = when(entry.get("replyAt"))
            thread.last_user_at = when(entry.get("lastUserAt"))
            thread.pending = int(entry.get("pending") or 0)
            thread.run_completed = when(entry.get("runCompletedAt"))
            thread.read = fresh
        if thread.active:
            # The tail read's count is from before this run started; only this run's
            # status read counts.
            fresh_status = entry.get("activeAt") == item.get("updatedAt")
            thread.pending = int(entry.get("activePending") or 0) if fresh_status else 0
        found.append(thread)
    return found


# ---------------------------------------------------------------- rows

@dataclass
class Row:
    kind: str  # decide, review, do, merge, flag
    title: str
    url: str | None
    machine: str
    what: str
    since: datetime | None
    blocks: int = 1
    flags: list = field(default_factory=list)
    pr: bool = False  # a PR row, which holds no agent
    related: list = field(default_factory=list)  # ids it touches: a thread's PRs, its coordinator
    options: list = field(default_factory=list)  # the thread's Next options, {key, class, text}

    def hours(self, now):
        return max(0.0, (now - self.since).total_seconds() / 3600) if self.since else 0.0

    def score(self, now):
        """Blocker-hours: how long Oliver has held it, times the agents it holds."""
        return self.hours(now) * self.blocks


def span(text) -> timedelta | None:
    total, matched = timedelta(), False
    for number, unit in SPAN.findall(text or ""):
        matched = True
        value = float(number)
        unit = unit.lower()
        total += timedelta(hours=value) if unit.startswith("h") else (
            timedelta(minutes=value) if unit.startswith("m") else timedelta(seconds=value))
    return total if matched else None


def unread_workers(coordinator, workers, now):
    """Workers that ended a run after the coordinator last ran, at least UNREAD_AFTER ago:
    replies it hasn't taken in, as Prefrontal's waitsOnCoordinator. Unlike Prefrontal, a
    worker that ended `done` counts too: its report is what the coordinator hasn't read,
    and a coordinator that never ran after it missed the completion wake."""
    if coordinator.active:
        return []
    seen = coordinator.ended
    found = []
    for worker in workers:
        if worker.active:
            continue
        ended = worker.reply_at or worker.run_completed
        if ended and (seen is None or ended > seen) and now - ended >= UNREAD_AFTER:
            found.append(worker)
    return found


def never_rewoken(thread, workers, now):
    """A `running` turn block whose thread went idle and stayed so past its ETA, or an
    hour when it has no ETA that is a time: the background work it waited on never woke it.
    Not while one of its workers runs. Returns when it was due, or None."""
    if thread.state != "running" or thread.active or not thread.reply_at:
        return None
    if any(worker.active for worker in workers):
        return None
    if thread.last_user_at and thread.last_user_at > thread.reply_at:
        return None
    eta = span((thread.turn or {}).get("eta"))
    due = thread.reply_at + (eta + UNREAD_AFTER if eta is not None else IDLE_LIMIT)
    return due if now > due else None


def related_ids(thread):
    """The ids a thread's row touches, for chief's Executor memory: its open PRs and, for a
    worker, its coordinator."""
    ids = [pr_url(pr.get("repo"), pr.get("number")) for pr in thread.prs if pr.get("repo") and pr.get("number")]
    if thread.worker_of:
        env, _, thread_id = thread.worker_of.partition("/")
        ids.append(link(env, thread_id))
    return ids


def pr_url(repo, number):
    return f"https://github.com/{repo}/pull/{number}"


def need_text(thread):
    if thread.pending and (thread.active or not thread.needs):
        return "Answer its pending question or approval in T3", "do"
    needs = thread.needs
    if needs:
        first = needs[0]
        more = f" (+{len(needs) - 1} more)" if len(needs) > 1 else ""
        return f"{first.get('kind', 'decide').capitalize()}: {first.get('name', '')}{more}", first.get("kind", "decide")
    return thread.headline or "waits on your reply", "decide"


def thread_rows(threads, projects, now):
    by_key = {thread.key: thread for thread in threads}
    workers: dict[str, list[Thread]] = {}
    for thread in threads:
        if thread.worker_of:
            workers.setdefault(thread.worker_of, []).append(thread)
    rows = []
    for thread in threads:
        mine = workers.get(thread.key, [])
        unread = unread_workers(thread, mine, now) if thread.coordinator or mine else []
        waiting_rows = [row for row in projects.get(thread.key, {}).get("workers", [])
                        if row["state"].lower().startswith("waiting")]
        blocked = 1 + max(len(unread), len(waiting_rows))
        # A pending request waits on Oliver even mid-run, as Prefrontal's waitingOn counts an
        # approval; T3's count doesn't say whether a question blocks, so every one counts.
        is_call = bool(thread.pending) or (not thread.active and (thread.state == "stop" or thread.needs))
        # D4: a worker's stop goes to its coordinator; only its T3 request is Oliver's.
        oliver_owns = not thread.worker_of and not thread.child
        if is_call and (oliver_owns or thread.pending):
            what, kind = need_text(thread) if oliver_owns else ("Answer its pending request in T3", "do")
            since = thread.updated if thread.active else thread.reply_at or thread.updated
            row = Row(kind, thread.title, thread.link, thread.machine, what, since, blocked,
                      related=related_ids(thread),
                      options=(thread.turn or {}).get("options") or [] if oliver_owns and not thread.active else [])
            if row.since and now - row.since > DAY:
                row.flags.append("over a day")
            if unread:
                row.flags.append(f"{len(unread)} worker repl{'y' if len(unread) == 1 else 'ies'} unread")
            rows.append(row)
        elif unread and not thread.active:
            since = min(worker.reply_at or worker.run_completed for worker in unread)
            names = ", ".join(worker.title for worker in unread[:3])
            rows.append(Row("flag", thread.title, thread.link, thread.machine,
                            f"Quiet coordinator: {len(unread)} worker repl{'y' if len(unread) == 1 else 'ies'} "
                            f"unread ({names})", since, len(unread), ["quiet coordinator"]))
        due = never_rewoken(thread, mine, now)
        if due and (oliver_owns or thread.worker_of):
            owner = by_key.get(thread.worker_of or "")
            note = f", so {owner.title} waits too" if owner else ""
            rows.append(Row("flag", thread.title, thread.link, thread.machine,
                            f"Never re-woken: said ⏳ {cut(plain(thread.headline), 60)}{note}", due,
                            2 if owner else 1, ["never re-woken"]))
    return rows


def project_rows(projects, threads, now):
    """project.md Workers rows a coordinator marked stuck or overdue."""
    by_key = {thread.key: thread for thread in threads}
    rows = []
    for coordinator_key, project in projects.items():
        coordinator = by_key.get(coordinator_key)
        for worker in project.get("workers", []):
            state = worker["state"].lower()
            if not (state.startswith("stuck") or state.startswith("overdue")):
                continue
            since = when(project.get("modified"))
            rows.append(Row("flag", f"◆ {project['project']}",
                            coordinator.link if coordinator else project.get("coordinator"),
                            coordinator.machine if coordinator else project.get("machine", "?"),
                            f"project.md marks {worker['worker']} {cut(worker['state'], 50)}", since, 1,
                            ["stuck worker"]))
    return rows


def pr_rows(prs, threads, called, now):
    """Oliver's PRs that wait on him with no thread asking about them: approved and green
    (his merge), or ready for review in a team's repo with no reviewer asked. A solo repo
    has no one to ask. `called` maps each thread with a call to its call's text; a PR it
    names by number is that call's, not a row of its own."""
    holders = {}
    for thread in threads:
        for pr in thread.prs:
            holders.setdefault(pr_key(pr.get("repo"), pr.get("number")), []).append(thread)
    rows = []
    for pr in prs:
        if pr["draft"]:
            continue
        name = pr_key(pr["repo"], pr["number"])
        held = holders.get(name, [])
        number = re.compile(rf"#?{pr['number']}(?!\d)")
        if any(number.search(called.get(thread.key, "")) for thread in held):
            continue  # its thread's own call already asks about it
        title = f"{short_repo(pr['repo'])} #{pr['number']}"
        machine = held[0].machine if held else "GitHub"
        if pr["review"] == "APPROVED" and pr["checks"] == "SUCCESS" and pr["mergeable"] != "CONFLICTING":
            rows.append(Row("merge", title, pr["url"], machine, f"Merge: approved and green · {cut(pr['title'], 50)}",
                            when(pr.get("approvedAt")) or when(pr.get("updatedAt")), 1, pr=True))
        elif pr.get("team", True) and not pr["reviewers"] and not pr["reviewed"]:
            rows.append(Row("flag", title, pr["url"], machine,
                            f"No reviewer: ready, nobody asked · {cut(pr['title'], 50)}",
                            when(pr.get("readyAt")) or when(pr.get("createdAt")), 1, ["no reviewer"], pr=True))
    return rows


def pr_key(repo, number):
    return f"{(repo or '').lower()}#{number}"


def short_repo(repo):
    return (repo or "").split("/")[-1]


def plain(headline):
    """A reply's headline without its leading marker and bold, to quote inside a row."""
    return short_title((headline or "").replace("**", ""))


def cut(text, longest):
    text = " ".join((text or "").split())
    return text if len(text) <= longest else text[:longest - 1].rstrip() + "…"


# ---------------------------------------------------------------- GitHub

QUERY = """
query($q: String!, $endCursor: String) {
  search(query: $q, type: ISSUE, first: 50, after: $endCursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url isDraft createdAt updatedAt reviewDecision mergeable
      repository { nameWithOwner owner { __typename } }
      reviewRequests(first: 10) { totalCount }
      latestReviews(first: 10) { nodes { state submittedAt author { __typename } } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      timelineItems(itemTypes: READY_FOR_REVIEW_EVENT, last: 1) {
        nodes { ... on ReadyForReviewEvent { createdAt } } }
    } }
  }
}"""


def open_prs():
    """Oliver's open PRs in every org, with review, CI, and reviewer state, every page.
    He had 110 open on Nov 2, 2026, past one search page."""
    out = subprocess.run(["gh", "api", "graphql", "--paginate", "--slurp", "-f", f"query={QUERY}",
                          "-f", "q=is:pr is:open author:@me archived:false"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "gh api graphql failed")
    return [read_pr(node) for page in json.loads(out.stdout) for node in page["data"]["search"]["nodes"] if node]


def read_pr(node):
    # A bot's review (CodeRabbit comments on every franklin-next PR) isn't a reviewer.
    reviews = [review for review in node["latestReviews"]["nodes"]
               if (review.get("author") or {}).get("__typename") != "Bot"]
    approvals = [review["submittedAt"] for review in reviews if review["state"] == "APPROVED"]
    rollup = (node["commits"]["nodes"] or [{}])[0].get("commit", {}).get("statusCheckRollup") or {}
    ready = node["timelineItems"]["nodes"]
    return {
        "repo": node["repository"]["nameWithOwner"], "number": node["number"], "title": node["title"],
        "url": node["url"], "draft": node["isDraft"], "createdAt": node["createdAt"],
        "updatedAt": node["updatedAt"], "review": node["reviewDecision"], "mergeable": node["mergeable"],
        "reviewers": node["reviewRequests"]["totalCount"], "reviewed": bool(reviews),
        "approvedAt": max(approvals) if approvals else None, "checks": rollup.get("state"),
        "readyAt": ready[0]["createdAt"] if ready else None,
        "team": node["repository"]["owner"]["__typename"] == "Organization",
    }


# ---------------------------------------------------------------- card

def age(hours):
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{round(hours)} h"
    return f"{round(hours / 24)} d"


def anchor(row):
    title = row.title.replace("[", "(").replace("]", ")")
    return f"[{title}]({'<' + row.url + '>' if row.url and row.url.startswith('t3-') else row.url})" \
        if row.url else title


def need_name(row):
    what = re.sub(r"^(Decide|Review|Do|Merge): ", "", row.what)
    return cut(f"{row.title}: {what}", 80)


def ranked(rows, now):
    """A thread's call holds a stopped agent; a PR row holds only the PR, so it ranks after."""
    return sorted(rows, key=lambda row: (row.pr, -row.score(now), -row.hours(now), row.title))


def headline(rows, now):
    """Leads with the oldest call that holds an agent, not a stale PR: "3 calls wait on you;
    ci-speed for 29 h", or for PR rows alone, how many wait and the oldest."""
    calls = [row for row in rows if not row.pr]
    if not calls:
        oldest = max(rows, key=lambda row: row.hours(now))
        verb = "PRs wait" if len(rows) != 1 else "PR waits"
        return f"🟡 **{len(rows)} {verb} on you; the oldest for {age(oldest.hours(now))}.**"
    oldest = max(calls, key=lambda row: row.hours(now))
    more = f", plus {len(rows) - len(calls)} PR{'s' if len(rows) - len(calls) != 1 else ''}" if len(calls) < len(rows) else ""
    verb = "calls wait" if len(calls) != 1 else "call waits"
    return (f"🟡 **{len(calls)} {verb} on you{more}; "
            f"{short_title(oldest.title)} for {age(oldest.hours(now))}.**")


def short_title(title):
    """A row's title without its leading status marks and ◆: "🟡 ◆ ci-speed" → "ci-speed"."""
    return re.sub(r"^[^\w#`\"'(\[]+", "", title).strip() or title


def card(rows, now, sources):
    """The ranked card in reply-shape's format: a headline, the top rows as notes, every
    row and the sources in one fold, a closing, and the turn block Prefrontal reads."""
    rows = ranked(rows, now)
    lines = []
    if not rows:
        lines.append("✅ **Nothing waits on you right now.**")
    else:
        flagged = sum(1 for row in rows if row.kind == "flag")
        lines.append(headline(rows, now))
        lines.append("")
        for row in rows[:NOTES]:
            lines.append(f"- {anchor(row)} · {cut(row.what, 60)} · {age(row.hours(now))}"
                         + (f" · holds {row.blocks}" if row.blocks > 1 else ""))
        if flagged:
            lines.append("")
            lines.append(f"{flagged} flag{'s' if flagged != 1 else ''} below no other view shows.")
    lines.append("")
    summary = f"All {len(rows)} ranked · {sources['summary']}"
    lines.append(f"<details><summary>{summary}</summary>")
    lines.append("")
    if rows:
        lines.append("| Rank | What waits | Where | Waiting | Holds | Flag |")
        lines.append("|---|---|---|---|---|---|")
        for rank, row in enumerate(rows, 1):
            what = cut(row.what, 90).replace("|", "\\|")
            lines.append(f"| {rank} | {anchor(row)}: {what} | {row.machine} | {age(row.hours(now))} | "
                         f"{row.blocks} | {', '.join(row.flags) or '-'} |")
        lines.append("")
    for line in sources["details"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append('Answer or snooze on the chief page, or here as "<rank or name>: <answer>" or '
                 '"<rank or name>: snooze <when>". chief passes your words on to the thread, and posts again on '
                 "its next run.")
    lines.append("")
    needs = [{"id": n, "kind": "review" if row.kind in ("flag", "merge") else row.kind, "name": need_name(row)}
             for n, row in enumerate(rows[:NEEDS], 1)]
    block = {"state": "stop", "needs": needs, "options": []} if needs else \
        {"state": "done", "needs": [], "options": []}
    lines.append("<!-- turn " + json.dumps(block, ensure_ascii=False, separators=(",", ":")).replace("-->", "->")
                 + " -->")
    return "\n".join(lines) + "\n"


def project_index(digests):
    """Every project.md digest keyed by its coordinator's thread key."""
    found = {}
    for machine, digest in digests:
        for project in digest.get("projects", []):
            coordinator = link_key(project.get("coordinator"))
            if coordinator:
                found[coordinator] = dict(project, machine=machine)
    return found


def object_id(row):
    """A row's id in chief's Executor memory: its thread or PR link, else project:<slug>."""
    return row.url or f"project:{row.title.lstrip('◆ ').strip()}"


def asleep(listed, snoozed):
    """The ids a card leaves out (D15): each thread T3 has snoozed, with its open PRs, and
    each PR or project Oliver snoozed in Executor (`snoozed`, from list_snoozes). A thread
    in `snoozed` doesn't count: T3 holds its snooze (D1), and wakes it on a new message."""
    ids = {item.lower() for item in snoozed if not thread_of(item)}
    for item in listed:
        if item.get("snoozed"):
            ids.add(link(item["env"], item["id"]).lower())
            ids.update(pr_url(pr.get("repo"), pr.get("number")).lower() for pr in item.get("prs") or [])
    return ids


def build(listed, cache, digests, prs, now, pr_error=None, mac_read=None, notes=(), record=None, snoozed=()):
    """The card. With `record`, a function that stores a run and returns a fold line, the run
    goes to chief's Executor memory first, and the card says whether it got there. `snoozed`
    holds the ids Oliver snoozed in Executor."""
    threads = threads_from(listed, cache)
    projects = project_index(digests)
    rows = thread_rows(threads, projects, now)
    calls = {row.url: row for row in rows if row.kind != "flag"}
    called = {thread.key: " ".join([calls[thread.link].what] + [need.get("name", "") for need in thread.needs])
              for thread in threads if thread.link in calls}
    rows += project_rows(projects, threads, now)
    rows += pr_rows(prs or [], threads, called, now)
    hidden = asleep(listed, snoozed)
    kept = [row for row in rows if object_id(row).lower() not in hidden]
    left_out, rows = len(rows) - len(kept), kept
    counts = {}
    for thread in threads:
        counts[thread.machine] = counts.get(thread.machine, 0) + 1
    machines = " · ".join(f"{name} {count} threads" for name, count in sorted(counts.items()))
    details = [f"Read {now.strftime('%Y-%m-%d %H:%M')} UTC: {machines}, "
               f"{len(prs or [])} open PR{'' if len(prs or []) == 1 else 's'}, {len(projects)} project.md files."]
    if mac_read:
        details.append(f"Mac project.md as of {mac_read}, from the Mac feed.")
    else:
        details.append("Mac project.md not read: the Mac feed has no output yet.")
    details += list(notes)
    sleeping = sum(1 for item in listed if item.get("snoozed") and item.get("title") not in OWN_TITLES)
    if sleeping or left_out:
        details.append("Snoozed, so left out until their time: "
                       + ", ".join(part for part in (sleeping and count(sleeping, "thread"),
                                                     left_out and count(left_out, "other row")) if part) + ".")
    if pr_error:
        details.append(f"PRs not read: {cut(pr_error, 120)}.")
    unread = [thread for thread in threads if not thread.read and not thread.active and thread.turn is None]
    if unread:
        details.append(f"{len(unread)} idle threads have no read yet, so they aren't ranked.")
    summary = f"{sum(1 for row in rows if row.kind == 'flag')} flags · {machines}"
    sources = {"summary": summary, "details": details}
    text = card(rows, now, sources)
    if record is None:
        return text
    run = run_input(ranked(rows, now), now, text, len(rows), summary, len(threads), len(prs or []),
                    sorted(counts))
    details.append(record(run))
    return card(rows, now, sources)


# ---------------------------------------------------------------- live feed (D16)
# The feeder (chief/feeder/feeder.mjs) streams each machine's T3 shell and reads a thread's
# projection when its run changes. It hands those facts to `inbox.py live`, so the calls it
# pushes to chief's app come from the same rules as the card's.

def live_read(item):
    """One feeder thread as (its threads.json row, the read merge takes): the shell's fields,
    and what a tail, status and first read would have found, from its projection's details.
    A thread the feeder hasn't read yet has only its shell; one whose reply has no turn
    block has turn None, so it makes no call."""
    row = {"env": item["env"], "id": item["id"], "title": item.get("title"), "status": item.get("status"),
           "createdBy": item.get("createdBy"), "updatedAt": item.get("updatedAt"),
           "snoozed": bool(item.get("snoozed")), "prs": item.get("prs") or []}
    pending = int(item.get("pending") or 0)
    read = {"env": item["env"], "id": item["id"], "updatedAt": item.get("updatedAt"), "activePending": pending}
    details = item.get("details")
    if isinstance(details, dict):
        reply = details.get("reply") or {}
        read.update(reply_facts(reply.get("text")), replyAt=reply.get("at"), lastUserAt=details.get("lastUserAt"),
                    pending=pending, runCompletedAt=item.get("runCompletedAt"),
                    workerOf=worker_line(details.get("first")))
    return row, read


def live_needs(items, digests, now):
    """The calls one machine's threads make, ranked, as record_live's items: the card's
    thread rows less its flags, which the hourly run keeps."""
    listed, reads = [], []
    for item in items:
        row, read = live_read(item)
        listed.append(row)
        reads.append(read)
    threads = threads_from(listed, merge({}, reads))
    rows = [row for row in thread_rows(threads, project_index(digests), now) if row.kind != "flag"]
    return [need_input(row) for row in ranked(rows, now)]


def digests_in(folder):
    """(every project.md digest by machine, the Mac feed's output or None)."""
    digests = [("devbox", {"projects": project_files.read_all(ORCHESTRATE)})]
    mac = load(folder / "mac-projects.json", None)
    if isinstance(mac, dict):
        digests.append(("Mac", mac))
    return digests, mac if isinstance(mac, dict) else None


# ---------------------------------------------------------------- Executor

def run_input(rows, now, text, count, summary, threads, prs, machines):
    """record_run's input for the chief Executor app (chief-app README, Tools): the card's
    rows in rank order, each Row mapped by name, except url → objectId and blocks → holds."""
    needs = [need_input(row) for row in rows]
    return {"readAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "state": "stop" if count else "done",
            "headline": text.split("\n", 1)[0].replace("**", ""), "summary": f"All {count} ranked · {summary}",
            "threads": threads, "prs": prs, "machines": machines, "card": text, "needs": needs}


def need_input(row):
    """One Row as a chief-app card item (record_run and record_live take the same shape)."""
    need = {"objectId": object_id(row), "kind": row.kind,
            "title": row.title, "what": row.what, "pr": row.pr, "machine": row.machine,
            "holds": row.blocks, "flags": row.flags, "related": row.related, "options": row.options}
    if row.since:
        need["since"] = row.since.strftime("%Y-%m-%dT%H:%M:%SZ")
    return need


def failure(output):
    """The line of a failed command that says why: a Node stack trace's `Error: …` line or an
    `HTTP nnn` message, else its last line, so the reason survives the cut."""
    lines = [line.strip().strip('",') for line in (output or "").splitlines() if line.strip()]
    if not lines:
        return "no output."
    reason = next((line for line in lines if re.search(r"\b\w*Error\b:|HTTP \d{3}", line)), lines[-1])
    reason = cut(re.sub(r'^"?message"?:\s*"?', "", reason), 120)
    return reason if reason.endswith(("…", ".")) else reason + "."


def record_with(command):
    """A recorder that runs chief-app's `bin/chief record_run -`. That script exits 1 on any
    failure, an MCP `isError`, a failed execution, or a bare HTTP 502, and prints why; a
    failure becomes the fold's line and never stops the card."""
    def record(run):
        try:
            out = subprocess.run([command, "record_run", "-"], input=json.dumps(run), capture_output=True,
                                 text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Not recorded in Executor: {failure(str(error))}"
        if out.returncode:
            return f"Not recorded in Executor: {failure(out.stderr or out.stdout)}"
        try:
            run_id = json.loads(out.stdout)["runId"]
        except (ValueError, KeyError, TypeError):
            return f"Not recorded in Executor: unreadable reply {cut(out.stdout, 80)}."
        return f"Recorded in Executor as {run_id}."
    return record


# ---------------------------------------------------------------- relay (stage 1)

# The one line chief adds to Oliver's words (D10): nothing else of its own.
PREFIX = "Oliver answered via chief:"


class ChiefError(RuntimeError):
    pass


def chief_call(tool, payload, command=None):
    """One chief-app tool through bin/chief; ChiefError carries the reason line."""
    command = command or str(Path(CHIEF_BIN).expanduser())
    try:
        out = subprocess.run([command, tool, "-"], input=json.dumps(payload), capture_output=True, text=True,
                             timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ChiefError(failure(str(error))) from None
    if out.returncode:
        raise ChiefError(failure(out.stderr or out.stdout))
    try:
        return json.loads(out.stdout)
    except ValueError:
        raise ChiefError(f"unreadable reply {cut(out.stdout, 80)}") from None


def thread_of(object_id):
    """(environmentId, threadId) of a T3 thread link, else None."""
    found = LINK.search(object_id or "")
    return (found.group(1), found.group(2)) if found else None


def message_for(answer, options):
    """Oliver's words verbatim under the prefix; a picked option also names its own text,
    which is the thread's words, not chief's."""
    option = next((item for item in options if item.get("key") == answer.get("key")), None)
    message = f"{PREFIX}\n{answer['text']}"
    if option and answer["text"].strip().lower() == option["key"]:
        message += f"\n\n({option['key']}: {option['text']})"
    return message


def thread_options(needs):
    """Each object's options. One thread can hold two rows, a call with options and a flag
    without, so the first non-empty list wins."""
    found = {}
    for need in needs:
        if need.get("options"):
            found.setdefault(need["objectId"], need["options"])
    return found


def relay_plan(answers, needs):
    """Each pending answer, oldest first, as a send ({kind: answer, answerId, environmentId,
    threadId, text, message}), a T3 snooze or unsnooze ({kind, answerId, environmentId,
    threadId, snoozedUntil?}), or a refusal ({answerId, refuse}) for an answer that has no
    thread or picks a stop:* option, which the page never offers (D12). Oldest first, so an
    undo lands after its snooze."""
    options = thread_options(needs)
    plans = []
    for answer in sorted(answers, key=lambda item: item.get("createdAt", 0)):
        where = thread_of(answer["objectId"])
        picked = next((item for item in options.get(answer["objectId"], []) if item.get("key") == answer.get("key")),
                      None)
        kind = answer.get("kind", "answer")
        if kind in ("snooze", "unsnooze"):
            if not where:
                # The app sends these at once; one still pending has nothing for T3 to do.
                plans.append({"answerId": answer["id"], "done": "hidden in Executor; no thread to snooze"})
                continue
            plan = {"kind": kind, "answerId": answer["id"], "environmentId": where[0], "threadId": where[1]}
            if kind == "snooze":
                plan["snoozedUntil"] = datetime.fromtimestamp(answer["until"] / 1000, timezone.utc) \
                    .strftime("%Y-%m-%dT%H:%M:%S.000Z")
            plans.append(plan)
        elif not where:
            plans.append({"answerId": answer["id"], "refuse": "not a thread: chief can only answer a T3 thread"})
        elif picked and str(picked.get("class", "")).startswith("stop:"):
            plans.append({"answerId": answer["id"],
                          "refuse": f"option {picked['key']} crosses a stop ({picked['class']}); answer it in the thread"})
        else:
            plans.append({"kind": "answer", "answerId": answer["id"], "environmentId": where[0], "threadId": where[1],
                          "text": answer["text"], "message": message_for(answer, options.get(answer["objectId"], []))})
    return plans


def resolve(item, needs):
    """The latest run's need an "<item>" names: its rank, or its name (case aside), whole
    or a unique part. None when nothing or more than one matches."""
    item = item.strip()
    if item.isdigit():
        return next((need for need in needs if need.get("rank") == int(item)), None)
    name = item.lower()
    whole = one_per_object(need for need in needs
                           if short_title(need["title"]).lower() == name or need["title"].lower() == name)
    if len(whole) == 1:
        return whole[0]
    part = one_per_object(need for need in needs if name in need["title"].lower())
    return part[0] if len(part) == 1 else None


def one_per_object(needs):
    """A thread's rows as one, the first, which ranks highest."""
    found = {}
    for need in needs:
        found.setdefault(need["objectId"], need)
    return list(found.values())


def parse_answer(line, needs):
    """ "<item>: <answer>" as (need, key, text). A name may hold ": ", so each split is tried,
    and the longest item that names a need wins. Raises ChiefError when no item matches or
    the answer can't be passed on."""
    splits = [(at, resolve(line[:at], needs)) for at in range(len(line)) if line.startswith(": ", at)]
    for at, need in sorted(((at, need) for at, need in splits if need), key=lambda pair: -pair[0])[:1]:
        text = line[at + 2:].strip()
        if not text:
            raise ChiefError("the answer is empty")
        if snooze.command(text):
            return need, None, text  # a snooze fits a PR row too, and picks no option
        if not thread_of(need["objectId"]):
            raise ChiefError(f"{need['title']} is a PR row with no thread to answer; answer it on GitHub")
        option = next((item for item in thread_options(needs).get(need["objectId"], []) if item["key"] == text.lower()),
                      None)
        if option and option["class"].startswith("stop:"):
            raise ChiefError(f"option {option['key']} on {need['title']} crosses a stop ({option['class']}); "
                             f"answer it in the thread")
        return need, option["key"] if option else None, text
    raise ChiefError('no item matches; write "<rank or name>: <answer>" with a rank or name from the last card')


def relay_command(args):
    if args.command == "mark":
        body = {"id": args.id, "status": args.status}
        if args.detail:
            body["detail"] = args.detail
        print(json.dumps(chief_call("mark_answer", body)))
        return 0
    inbox = chief_call("list_open_needs", {})
    needs = inbox.get("needs", [])
    if args.command == "answer":
        # A snoozed item is off the card but can still be named, to unsnooze or answer it.
        named = needs + [{"objectId": item["objectId"], "title": item.get("title") or item["objectId"], "rank": None}
                         for item in inbox.get("snoozed", [])]
        need, key, text = parse_answer(args.line, named)
        asleep_ids = {item["objectId"] for item in inbox.get("snoozed", [])}
        print(json.dumps(chat_answer(need, key, text, datetime.now(timezone.utc), asleep_ids=asleep_ids),
                         ensure_ascii=False))
        return 0
    answers = chief_call("list_answers", {"status": "pending", "kind": "any"}).get("answers", [])
    for plan in relay_plan(answers, needs):
        if "refuse" in plan or "done" in plan:
            chief_call("mark_answer", {"id": plan["answerId"], "status": "failed" if "refuse" in plan else "sent",
                                       "detail": plan.get("refuse") or plan["done"]})
            continue
        print(json.dumps(plan, ensure_ascii=False))
    return 0


def chat_answer(need, key, text, now, call=None, asleep_ids=None):
    """Record one answer Oliver typed: his words, or a snooze or unsnooze when they are one
    (D15). `asleep_ids` holds the snoozed object ids list_open_needs gave; an unsnooze of
    anything else is refused here, since the app's own refusal arrives as a bare 502.
    Returns what chief tells him, {answerId, item, kind, …}."""
    call = call or chief_call
    action = snooze.command(text)
    if action and action[0] == "snooze":
        if not action[1]:
            raise ChiefError(f'say when: "<item>: snooze <when>", such as {snooze.FORMS}')
        try:
            end = snooze.until(action[1], now)
        except snooze.Unparsed as error:
            raise ChiefError(str(error)) from None
        made = call("snooze", {"objectId": need["objectId"], "until": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
        local = end.astimezone(snooze.zone())
        return {"answerId": made["id"], "item": need["title"], "kind": "snooze",
                "until": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "local": f"{local:%a %d %b %H:%M %Z}",
                "status": made["status"]}
    if action:
        if asleep_ids is not None and need["objectId"] not in asleep_ids:
            raise ChiefError(f"{need['title']} isn't snoozed")
        made = call("unsnooze", {"objectId": need["objectId"]})
        return {"answerId": made["id"], "item": need["title"], "kind": "unsnooze", "status": made["status"]}
    body = {"objectId": need["objectId"], "text": text}
    if key:
        body["key"] = key
    made = call("answer", body)
    return {"answerId": made["id"], "item": need["title"], "kind": "answer", "key": key, "text": text}


def main(argv):
    parser = argparse.ArgumentParser(prog="inbox.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the t3_thread_list calls still to make; with none left, write threads.json")
    commands.add_parser("plan", help="the t3_thread_read calls still to make")
    commands.add_parser("relay", help="plan the sends for Oliver's pending answers, refusing what can't go")
    mark = commands.add_parser("mark", help="mark an answer sent or failed after its send")
    mark.add_argument("id")
    mark.add_argument("status", choices=("sent", "failed"))
    mark.add_argument("detail", nargs="?")
    answer = commands.add_parser("answer", help='record Oliver\'s "<item>: <answer>" or "<item>: snooze <when>" '
                                               'from the chief thread')
    answer.add_argument("line")
    commands.add_parser("live", help='one machine\'s threads from the feeder on stdin, {"env", "threads"}; '
                                     'prints {"machine", "needs"}, the calls they make, for record_live')
    card_args = commands.add_parser("card")
    card_args.add_argument("--no-gh", action="store_true", help="skip GitHub, as tests do")
    card_args.add_argument("--now", help="ISO time to rank against; default now")
    card_args.add_argument("--no-record", action="store_true", help="skip Executor, as tests do")
    card_args.add_argument("--note", action="append", default=[],
                           help="a line for the fold's sources, such as a machine that didn't answer")
    args = parser.parse_args(argv)
    if args.command in ("relay", "mark", "answer"):
        try:
            return relay_command(args)
        except ChiefError as error:
            print(f"inbox.py {args.command}: {error}", file=sys.stderr)
            return 1
    folder = state_dir()
    if args.command == "live":
        feed = json.load(sys.stdin)
        now = when(feed.get("now")) or datetime.now(timezone.utc)
        env = str(feed.get("env") or "")
        print(json.dumps({"machine": MACHINES.get(env, env[:8]),
                          "needs": live_needs(feed.get("threads") or [], digests_in(folder)[0], now)},
                         ensure_ascii=False))
        return 0
    try:
        calls = turn_calls()
    except tool_results.Unavailable as error:
        if args.command != "card":
            print(f"inbox.py {args.command}: {error}", file=sys.stderr)
            return 1
        calls, unread = [], f"No reads this run: {error}."
    else:
        unread = None
    if args.command == "list":
        try:
            threads, notes, missing = listing(calls)
        except ChiefError as error:
            print(f"inbox.py list: {error}", file=sys.stderr)
            return 1
        for args_ in missing:
            print(json.dumps(args_, separators=(",", ":")))
        if not missing:
            (folder / "threads.json").write_text(json.dumps(threads, indent=1, ensure_ascii=False))
            (folder / "notes.json").write_text(json.dumps(notes, ensure_ascii=False))
            print(f"inbox.py list: wrote {len(threads)} threads to threads.json"
                  + "".join(f"; {note}" for note in notes), file=sys.stderr)
        return 0
    listed = load(folder / "threads.json", None)
    if not isinstance(listed, list):
        print(f"inbox.py: run `inbox.py list` first (SKILL.md, List)", file=sys.stderr)
        return 1
    cache = load(folder / "cache.json", {})
    reads, missing, failed = gather(plan(listed, cache), calls)
    if args.command == "plan":
        for args_ in missing:
            print(json.dumps(args_, separators=(",", ":")))
        return 0
    notes = [note for note in load(folder / "notes.json", []) if isinstance(note, str)] + list(args.note)
    if unread:
        notes.append(unread)
    if missing:
        notes.append(f"{count(len(missing), 'planned read')} not made, so {keeps(len(missing))}.")
    if failed:
        notes.append(f"{count(len(failed), 'read')} failed, so {keeps(len(failed))}: {cut(failed[0], 80)}")
    merge(cache, reads)
    (folder / "cache.json").write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    feed = feed_projects(calls)
    if feed is not None:
        (folder / "mac-projects.json").write_text(json.dumps(feed, indent=1, ensure_ascii=False))
    now = when(args.now) if args.now else datetime.now(timezone.utc)
    digests, mac = digests_in(folder)
    prs, pr_error = [], None
    if not args.no_gh:
        try:
            prs = open_prs()
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            pr_error = str(error)
    record, snoozed = None, []
    if not args.no_record:
        record = record_with(str(Path(CHIEF_BIN).expanduser()))
        try:
            snoozed = [item["objectId"] for item in chief_call("list_snoozes", {}).get("snoozes", [])]
        except ChiefError as error:
            notes.append(f"Snoozes not read from Executor, so snoozed PRs show: {error}")
    print(build(listed, cache, digests, prs, now, pr_error, mac.get("read") if mac else None,
                notes, record, snoozed), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

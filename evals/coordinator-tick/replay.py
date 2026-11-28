"""Replays the kit's real project.tick() over the recorded coordinator heartbeats in OUT.
At each 10-minute step of one global grid, as a timer fires, it synthesizes what `t3 thread
show` and `gh pr view` would have returned then, from T3's run, item and request history
(dbdump.py) and GitHub's PR timelines (timelines.py), and the Workers rows the coordinator
would have had, and calls tick() with the saved state. Writes OUT/replay.json.
usage: replay.py OUT KIT_COORDINATOR_SCRIPTS_DIR"""
import collections, glob, json, re, sys
from datetime import datetime
from urllib.parse import unquote

sys.path.insert(0, sys.argv[2])
import project  # the kit's coordinator script, whose tick() is replayed

STEP = 600  # the timer's interval
LIVE = 48 * 3600  # how long a finished run or a PR mention stays on a row
OUT = sys.argv[1].rstrip("/") + "/"


def ts(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def norm(thread):
    return unquote(thread).removeprefix("thread:")


turns = json.load(open(OUT + "turns.json"))
history = {k: v for f in glob.glob(OUT + "hist_*.json") for k, v in json.load(open(f)).items()}
timelines = {(repo, n): events for repo, n, events in json.load(open(OUT + "timelines.json")) if events is not None}
starts_by_sess = json.load(open(OUT + "starts.json"))
mentions = collections.defaultdict(list)
for sess, repo, n, times in json.load(open(OUT + "pr_mentions.json")):
    mentions[sess].append(((repo, n), times))
files = {x["file"].split("/")[-1][:-6]: x["file"] for x in turns if x["sched"]}


def records(path):
    """Each transcript line outside a heartbeat turn, with its time: what the coordinator saw."""
    lines, in_heartbeat = [], False
    for line in open(path, errors="replace"):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        content = (record.get("message") or {}).get("content")
        if record.get("type") == "user" and not record.get("isMeta"):
            if isinstance(content, str):
                in_heartbeat = content.lstrip().startswith("Coordinator heartbeat")
            elif isinstance(content, list) and not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                in_heartbeat = any(isinstance(c, dict) and c.get("type") == "text"
                                   and c.get("text", "").lstrip().startswith("Coordinator heartbeat") for c in content)
        if record.get("timestamp") and not in_heartbeat:
            lines.append((ts(record["timestamp"]), unquote(line)))
    return lines


sightings = [r for path in files.values() for r in records(path)]


def pr_at(events, at):
    """[state, isDraft] of a PR at time `at`, from its timeline."""
    state, draft, first = "OPEN", None, None
    for e in sorted(events, key=lambda e: e["t"] or ""):
        if not e["t"]:
            continue
        if first is None and e["e"] in ("ready_for_review", "convert_to_draft"):
            first = e["e"]
        if ts(e["t"]) > at:
            continue
        if e["e"] == "merged":
            state = "MERGED"
        elif e["e"] == "closed" and state != "MERGED":
            state = "CLOSED"
        elif e["e"] == "reopened":
            state = "OPEN"
        elif e["e"] == "ready_for_review":
            draft = False
        elif e["e"] == "convert_to_draft":
            draft = True
    if draft is None:
        draft = first == "ready_for_review"
    return [state, draft]


def view(ref, at):
    """The PR as project.view_pr reads it. The timelines hold no pushes, so its head never moves."""
    repo, n = ref.split("#")[0], int(ref.split("#")[1])
    if timelines.get((repo, n)) is None:
        return None
    state, draft = pr_at(timelines[(repo, n)], at)
    return project.Pull(state, bool(draft), ref)


rows_out = []
for sess in sorted(files):
    hist = history.get(sess)
    if not hist:
        continue
    coord = hist["coord"]
    heartbeat_times = [x["t"] for x in turns if x["sched"] and x["file"].endswith(sess + ".jsonl")]
    # the coordinator's own runs, other than heartbeats: while one runs, the tick holds
    coord_runs = [(ts(a), ts(c) if c else 9e18) for _, _, a, c in hist["threads"].get(coord, {}).get("runs", [])
                  if not any(abs(ts(a) - t) < 90 for t in heartbeat_times)]
    starts = collections.defaultdict(list)
    for t0, thread, _ in starts_by_sess.get(sess, []):
        starts[norm(thread)].append(t0)
    workers = []
    for tid, thread in hist["threads"].items():
        if tid == coord:
            continue
        started = starts.get(norm(tid), [])
        all_runs = [(ordinal, status, ts(a), ts(c) if c else None) for ordinal, status, a, c in thread["runs"]]
        mine = [r for r in all_runs if any(x - 10 <= r[2] <= x + 300 for x in started)]
        if not mine:
            continue
        task_key = norm(tid).split("delegate-task:")[-1] if "delegate-task:" in norm(tid) else norm(tid)
        title_key = f"({thread['title']}) ["
        workers.append(dict(id=tid, slug=re.sub(r"\W+", "-", thread["title"])[:30] or "w", all=all_runs, mine=mine,
                            seen=sorted(x for x, line in sightings if task_key in line or title_key in line),
                            items=sorted(ts(i + ":00Z") for i in thread["items"]),
                            reqs=[(ts(a), ts(b) if b else 9e18) for a, b in thread["reqs"]]))
    heartbeats = sorted([x for x in turns if x["sched"] and x["prompt"].startswith("Coordinator heartbeat")
                         and x["file"].endswith(sess + ".jsonl")], key=lambda x: x["t"])
    state, prev, woken = {}, None, collections.defaultdict(list)
    for x in heartbeats:
        t = x["t"]
        t0 = max(prev, t - 3 * 3600) if prev else t - 3600
        grid = [k * STEP for k in range(int(t0 // STEP) + 1, int(t // STEP) + 1)]  # one global grid, as a timer fires
        wakes = []
        for g in sorted(grid):
            busy = any(a <= g <= c for a, c in coord_runs)
            rows = []
            show = {"lead": {"status": "running" if busy else "completed", "runCount": 1, "itemCount": 1,
                             "pendingRequestCount": 0}}
            for w in workers:
                active = [r for r in w["all"] if r[2] <= g and (r[3] is None or r[3] > g)]
                ended = [r for r in w["all"] if r[3] and r[3] <= g]
                seen_after = lambda e: any(e <= s <= g for s in w["seen"]) or any(e <= s <= g for s in woken[w["id"]])
                mine_started = [r for r in w["mine"] if r[2] <= g]
                if not mine_started:
                    continue
                last = max(mine_started, key=lambda r: r[2])
                if active:
                    row_state = "running"
                elif last[3] and last[3] > g - LIVE and not seen_after(last[3]):
                    row_state = "running"  # it ended, but the coordinator hasn't seen that yet
                else:
                    continue
                status = active[-1][1] if active else max(ended, key=lambda r: r[3])[1]
                if active:
                    status = "running"
                pending = sum(1 for a, b in w["reqs"] if a <= g < b)
                if pending:
                    status = "waiting"
                show[w["id"]] = {"status": status, "runCount": sum(1 for r in w["all"] if r[2] <= g),
                                 "itemCount": sum(1 for i in w["items"] if i <= g), "pendingRequestCount": pending}
                rows.append(f"| {w['slug']} | <t3-thread://v2/env/{w['id']}> | — | {row_state} | — | — |")
            # each tracked PR, with the state the coordinator saw when it first mentioned it, as rows record it
            refs = [f"{repo}#{n}" + (" " + pr_at(timelines[(repo, n)], times[0])[0]
                                     if (repo, n) in timelines and pr_at(timelines[(repo, n)], times[0])[0] != "OPEN" else "")
                    for (repo, n), times in mentions[sess] if any(g - LIVE <= y <= g for y in times)]
            md = ["# ◆ p", "", "Coordinator: <t3-thread://v2/env/lead> · Checkout: /nonexistent · Mode: m", "",
                  "## Workers", "", "| Worker | Thread | Branch or PR | State | Waits on | Last side effect |",
                  "|---|---|---|---|---|---|", *rows,
                  # tracked PRs on an open row: the coordinator unwatches a finished PR on its first wake
                  f"| prs | — | {' · '.join(refs) or '—'} | waiting | — | — |", "",
                  "## Listening", "", "- Heartbeat: tick", ""]
            # The recordings hold no T3 watch state, so every tracked PR counts as watched: the
            # replay measures the tick's other wakes, and never reads this machine's T3 database.
            watched = {ref.split(" ")[0].lower() for ref in refs}
            result = project.tick(md, state, g, show=lambda i: show.get(i), view=lambda ref: view(ref, g),
                                  watching=lambda _: watched)
            if result is None:
                continue
            due, state = result
            if due:
                wakes.append((g, [line for _, line in due]))
                for key, _ in due:
                    if key.startswith("ended:") or key.startswith("asked:"):
                        woken[key.split(":", 1)[1].rsplit(":", 1)[0]].append(g)
        rows_out.append(dict(sess=sess, t=t, ctx=x["ctx"], act_s=x["act_s"], out=x["out"], wakes=wakes,
                             reply=x["reply"][:300], tools=[a[:120] for a in x["tools"]]))
        prev = t
json.dump(rows_out, open(OUT + "replay.json", "w"))
print("done", len(rows_out), "gate wakes", sum(len(r["wakes"]) for r in rows_out))

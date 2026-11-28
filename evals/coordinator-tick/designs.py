"""Compares heartbeat designs on the data replay.py used, for the Franklin coordinators:
E0 (no heartbeat: only T3's wakes and the user), E1 (a `once` deadline per worker run,
re-armed while it runs), and E3 (a fresh Haiku scheduled task that runs the tick).
The tick itself (addystack #67) is replay.py's and analyze.py's result.

- E0: for each acting heartbeat, how long until the coordinator's next wake that isn't a
  heartbeat, and until its next message that isn't a T3 notification or scheduled task.
- E1: the worker runs the coordinators started, each counted once, how long each ran,
  and how many times a deadline of D minutes would have fired on a run still working.
- E3: one run per 10-minute step per machine, at a fresh Haiku run's measured cost.
- Silent workers: the replay's non-PR tick findings, by kind.
usage: designs.py OUT"""
import collections, json, statistics, sys
from datetime import datetime, timezone
from heartbeats import kind, load

OUT = sys.argv[1].rstrip("/") + "/"
DELIVERY = ("Delegated task", "Update on pull request", "<task-notification>", "<command-message>", "Continue where")
# A fresh Haiku session that runs one Bash command, measured on six such T3 runs on the
# Mac (2026-11): median 3 model calls, 91.7k context tokens, 868 output tokens, 11.7 s.
HAIKU_RUN = {"ctx": 91_700, "out": 868, "secs": 11.7}
STEP_S = 600


def iso(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def at(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%m-%d %H:%M")


rows, turns, files, starts, legacy, franklin = load(OUT)
sessions = {r["sess"] for r in franklin}
by_sess = collections.defaultdict(list)
for t in turns:
    sess = t["file"].split("/")[-1][:-6]
    if sess in sessions:
        by_sess[sess].append(t)
for v in by_sess.values():
    v.sort(key=lambda t: float(t["t"]))


def heartbeat(t):
    return t["prompt"].startswith("Coordinator heartbeat")


print(f"== E0, no heartbeat: each acting heartbeat's wait for the coordinator's next other wake, "
      f"and for its next message that isn't a T3 notification (the user's, or another agent's send)")
for r in sorted((r for r in franklin if r["acted"]), key=lambda r: float(r["t"])):
    later = [t for t in by_sess[r["sess"]] if float(t["t"]) > float(r["t"]) and not heartbeat(t)]
    wake = later[0] if later else None
    user = next((t for t in later if str(t["sched"]) != "True" and not t["prompt"].startswith(DELIVERY)), None)
    wait = lambda t: "none" if t is None else f"{(float(t['t']) - float(r['t'])) / 60:.0f} min"
    print(f"   {files[r['sess']].split('/')[-2][-24:]:24} {at(r['t'])}  wake {wait(wake):>9}  message {wait(user):>9}"
          f"  · {r['reply'][:70]!r}")

runs = collections.defaultdict(list)
for host in ("mac", "devbox"):
    try:
        hist = json.load(open(OUT + f"hist_{host}.json"))
    except FileNotFoundError:
        continue
    for v in hist.values():
        for tid, th in v["threads"].items():
            runs[tid] += [(iso(a), iso(b), status) for _, status, a, b in th["runs"] if a and b]
matched, unmatched = {}, 0
for sess in sorted(sessions):
    for t, tid, _ in starts.get(sess, []):
        near = [(k, x) for k in (tid, tid.split(":")[-1]) for x in runs.get(k, []) if abs(x[0] - t) < 300]
        if near:
            k, x = min(near, key=lambda kx: abs(kx[1][0] - t))
            matched[(k.split(":")[-1], x[0])] = x  # a run two starts both match counts once
        else:
            unmatched += 1
lengths = sorted((b - a) / 60 for a, b, _ in matched.values())
ends = collections.Counter(status for _, _, status in matched.values())
print(f"\n== E1, a deadline per worker run: {len(lengths)} runs ({unmatched} starts matched no run), "
      f"ended {dict(ends)}")
print(f"   minutes: median {statistics.median(lengths):.1f}, p90 {lengths[int(.9 * len(lengths))]:.0f}, "
      f"max {lengths[-1]:.0f}")
for d in (30, 60, 90):
    fires = sum(int(x // d) for x in lengths)
    print(f"   deadline {d} min: fires {fires} times on a run still working; "
          f"{2 * len(lengths) + fires} create, re-arm, and delete calls in the coordinator")

steps = (max(float(r["t"]) for r in rows) - min(float(r["t"]) for r in rows)) / STEP_S
print("\n== E3, a fresh Haiku task that runs the tick")
for every, n in ((10, steps), (60, steps / 6)):
    print(f"   every {every} min: {n:.0f} runs, {n * HAIKU_RUN['ctx'] / 1e9:.3f}B context tokens, "
          f"{n * HAIKU_RUN['out'] / 1e6:.2f}M output, {n * HAIKU_RUN['secs'] / 3600:.1f} h elapsed per machine")

kinds = collections.Counter()
for r in franklin:
    for _, lines in r["wakes"]:
        for line in lines:
            k = kind(line)
            if k != "pr":
                kinds[line.split("stopped (")[1].split(")")[0] if k == "stopped" else k] += 1
print(f"\n== Silent workers the tick reports (Franklin): {dict(kinds) or 'none'}")

"""Summarizes OUT/replay.json: for each group of coordinators, today's heartbeat turns
against the turns the tick would have caused, and each acting heartbeat it didn't wake.
A heartbeat acted when it delegated, sent to a thread, loaded a skill, edited a file
outside the project folder, committed, pushed, or merged. Every acting heartbeat keeps its
real cost; each further tick wake costs that coordinator's median no-op heartbeat. A
coordinator whose started runs went mostly to `t3_thread_launch` threads, which wake no
one when they end, is grouped apart as legacy.
usage: analyze.py OUT"""
import collections, statistics, sys
from datetime import datetime, timezone
from heartbeats import kind, load

OUT = sys.argv[1].rstrip("/") + "/"
rows, _, files, starts, legacy, franklin = load(OUT)


def report(name, group):
    if not group:
        return
    noop = collections.defaultdict(list)
    for r in group:
        if not r["acted"]:
            noop[r["sess"]].append(r)
    med = {s: [statistics.median(r[k] for r in (noop[s] or [r for r in group if r["sess"] == s])) for k in ("ctx", "act_s", "out")]
           for s in {r["sess"] for r in group}}
    extra = [(r["sess"], max(0, len(r["wakes"]) - r["acted"])) for r in group]
    acted = [r for r in group if r["acted"]]
    today = [len(group), sum(r["act_s"] for r in group) / 3600, sum(r["ctx"] for r in group) / 1e9]
    gated = [len(acted) + sum(n for _, n in extra),
             (sum(r["act_s"] for r in acted) + sum(n * med[s][1] for s, n in extra)) / 3600,
             (sum(r["ctx"] for r in acted) + sum(n * med[s][0] for s, n in extra)) / 1e9]
    signals = collections.Counter(kind(line) for r in group for _, lines in r["wakes"] for line in lines)
    print(f"== {name}: {len(group)} heartbeats, {len(acted)} acted ({sum(1 for r in acted if r['wakes'])} with a tick wake "
          f"in their window), {sum(len(r['wakes']) for r in group)} tick wakes")
    print("   today:  %d turns, %.2f model-h, %.3fB context tokens" % tuple(today))
    print("   ticked: %d turns, %.2f model-h, %.3fB context tokens" % tuple(gated))
    print("   saved:  %d turns (%.0f%%), %.2f h, %.3fB (%.0f%%)" % (today[0] - gated[0], 100 * (1 - gated[0] / today[0]),
          today[1] - gated[1], today[2] - gated[2], 100 * (1 - gated[2] / today[2])))
    print("   wake lines:", dict(signals))
    for r in acted:
        if not r["wakes"]:
            at = datetime.fromtimestamp(r["t"], timezone.utc).strftime("%m-%d %H:%M")
            print(f"   no wake: {r['sess'][:8]} {at} · {r['reply'][:110]!r}")


report("Franklin coordinators", franklin)
report("other current coordinators", [r for r in rows if r not in franklin and r["sess"] not in legacy])
report("legacy t3_thread_launch coordinators", [r for r in rows if r["sess"] in legacy])

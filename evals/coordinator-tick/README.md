# coordinator-tick evals

Replays the kit's real `project.py tick` (the coordinator's scripted heartbeat) over
recorded coordinator heartbeats, and counts the model turns it would have caused against
the hourly `schedule_task` heartbeat's. Rerun it after changing what the tick reports, or
what T3 itself delivers (PR watches, child completions), to see what the change costs and
which acting heartbeats it stops waking.

At each step of one 10-minute grid, as the timer fires, `replay.py` rebuilds what `t3
thread show` and `gh pr view` would have returned then, from T3's run, item, and request
history and GitHub's PR timelines. It also rebuilds the Workers rows the coordinator would
have had: a worker the coordinator started stays `running` until a record outside a
heartbeat turn names it after its run ended (T3's completion message, a read, a send).
Then it calls `tick()` with the saved state.

```sh
OUT=/tmp/coordinator-tick
python3 collect.py $OUT mac=~/.claude/projects devbox=/path/to/devbox/projects-copy
python3 dbdump.py ~/.t3/userdata/statev2.sqlite < $OUT/refs_mac.json > $OUT/hist_mac.json
ssh devbox 'cat > /tmp/dbdump.py' < dbdump.py
ssh devbox 'python3 /tmp/dbdump.py ~/.t3/userdata/statev2.sqlite' < $OUT/refs_devbox.json > $OUT/hist_devbox.json
python3 timelines.py $OUT
python3 replay.py $OUT ../../skills/orchestrator/coordinator/scripts 2>/dev/null
python3 analyze.py $OUT
python3 designs.py $OUT
```

`dbdump.py` opens T3's database read-only. A machine's projects copy comes from
`rsync devbox:.claude/projects/ <copy>`; only top-level session files with a `Coordinator
heartbeat` prompt are read, from 2026-10-29 on (`SINCE` in `collect.py`).

## What limits the numbers

- **Workers rows are inferred**, since `project.md` has no history. A row is `running`
  from the coordinator's start of a run until it next names that thread outside a
  heartbeat turn. A coordinator whose own turn failed (a rate limit) counts as having seen
  a message it never handled, so the tick's hourly repeat for that row isn't replayed.
- **The heartbeats' own actions stay in the history.** When a recorded heartbeat restarted
  an interrupted worker, the replay sees it running again, though without that heartbeat
  the tick would still see it stopped and report it on its next step.
- **PRs are the ones the coordinator named** in the last 48 hours (URLs, or a bare `#5NNN`
  in a Franklin project), on one open row, with the state the coordinator saw when it first
  named them. A real project tracks only its rows' PRs. The recordings hold no T3 watch
  state, so the replay counts every tracked PR as watched.
- **A tick wake's cost is the coordinator's median no-op heartbeat**, and an acting
  heartbeat keeps its real cost. "With a tick wake in its window" means any wake in the
  hour before it, not one with the cause it acted on.
- **Turns are counted per Claude transcript**; a forked session's copies are deduplicated
  by time and prompt.

## Result, 2026-11-12 (addystack #67 at ad37a76)

```text
== Franklin coordinators: 481 heartbeats, 13 acted (4 with a tick wake in their window), 58 tick wakes
   today:  481 turns, 6.00 model-h, 0.422B context tokens
   ticked: 67 turns, 0.70 model-h, 0.080B context tokens
   saved:  414 turns (86%), 5.31 h, 0.342B (81%)
```

The 9 acting heartbeats without a wake, and why each is safe or out of scope, are in the
r119 report (`~/.local/state/orchestrate/reports/suite-audit-r119-heartbeats-*.md`).
Coordinators that ran `t3_thread_launch` workers, which wake no one when they end, get
more turns, one per worker run, as `delegate_task` workers already give.

## Other designs (`designs.py`)

`designs.py` reads the same files and compares designs without the tick: E0 (no
heartbeat), E1 (a `once` deadline per worker run), and E3 (a fresh Haiku scheduled task
that runs the tick). Run it after `replay.py`.

- **E0's waits are measured from the heartbeat**, not from the event it acted on, which
  came earlier. "wake" is the coordinator's next turn that isn't a heartbeat. The script
  doesn't trace what caused that turn: it may be unrelated to the event, or caused by the
  heartbeat's own action, which E0 wouldn't have taken (11-04 20:05 is one). "message" is
  the next turn that isn't a T3 notification or a scheduled task: the user's, or another
  agent's send. It may be the user answering the heartbeat's own card.
- **E1 counts each run once**, matching each start to the nearest run within 5 minutes.
  A fire is a deadline reached by a run still working, a false alarm, for a fixed
  deadline re-armed on each fire. The coordinator makes one call to create, re-arm, or
  delete each deadline.
- **E3's cost per run is a constant** measured from six fresh Haiku T3 runs that each ran
  one Bash command (`HAIKU_RUN`). Two of those six had the command blocked by a hook.

Result, 2026-11-13:
- **E0:** 1–132 min to the next other wake, and 21 min to 39 h to the next message.
- **E1:** 570 runs; a 60-minute deadline fires 23 times, with 1,163 calls.
- **E3:** 0.183B Haiku context tokens per machine every 10 minutes, and 0.031B hourly.
- **The tick's silent-worker findings for Franklin:** 2 interrupted runs, 2 cancelled runs, and 5 completed runs whose row still said running. No stuck finding.

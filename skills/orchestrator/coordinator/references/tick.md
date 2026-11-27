# Tick

A timer on each machine runs `scripts/tick.sh` every 10 minutes. For every project folder
under `~/.local/state/orchestrate/` whose Listening Heartbeat is `tick`, it runs
`scripts/project.py <folder> tick --send`, which reads `project.md`, checks the live rows'
threads with `t3 thread show` and their PRs with `gh pr view`, and sends the coordinator's
thread a `<coordinator-tick>` message with `t3 thread send` only when there is news.
Nothing changed, nothing is sent, and no model runs. T3's scheduler can't run a script
without starting a model turn, which is why this is an OS timer and not a `schedule_task`.

## What counts as news

T3 already wakes the coordinator for a `delegate_task` child that completes, a pending
question, and a watched PR's checks, comments, reviews, and conflicts. The tick covers
the rest:

- **Stopped**: a row says `running`, `overdue`, or `unknown`, and its thread stopped and
  stayed stopped through a whole tick: a failed or interrupted run T3 didn't deliver, a
  `t3_thread_launch` worker that finished, or a completion whose row nobody updated.
- **Asked**: the same, for a thread holding a pending question.
- **Stuck**: a running thread with no new item for an hour.
- **Elsewhere**: a live row whose link names another machine's environment, which
  `t3 thread show` can't read: an hourly reminder to read it.
- **PR**: a PR any Workers row names, whatever its State, merged, closed, or turned
  ready or draft since the tick last saw it. The first look at a PR only records it, and
  one it saw merged or closed isn't read again.
- **Unwatched**: an open Worker PR, draft or not, that T3 won't wake this thread on: no
  watch, or a stack-dismissed one. T3 ends a thread's watches unannounced when the user
  stops or rolls back a turn. Call `watch_pull_request` on it. When T3's state database
  can't be read, the tick skips this check and logs why.
- **Owner**: a ref the tick can't resolve to one repo: a word then `#N` (`web #20`),
  `repo#N` for a repo other than the checkout's, a `#N` an arrow joins to such a ref, or a
  `#N` once the checkout is gone or has no GitHub origin. `#N`, the checkout's own `repo#N`, and a range `#20–#22` resolve
  through its origin; `owner/repo#N` and a URL need no checkout.
- **Unreadable**: a row with a cell that starts with a live state but whose cells don't
  match the Workers header, or a live row with no thread link.

Each finding except a PR change repeats hourly while it holds, so fixing the row or
the watch stops it.
While the coordinator's own thread runs, the tick still times its workers but sends
nothing and leaves PRs for later, so its turn settles first. `tick.json` beside
`project.md` holds what it last saw; a failed send leaves it unchanged, so the next tick
sends again. A thread or PR it can't read is named on stderr, in the timer's log, with the time
and the CLI's reason. A copy of a project whose coordinator is on another machine's
environment is skipped: T3 here can't read that thread, and that machine's timer ticks it.

## Install

Once per machine, from the coordinator skill's folder. Check that it runs with
`project.py <folder> tick`, which warns while the timer hasn't run in 20 minutes.

macOS:

```sh
python3 -c 'import plistlib, sys
sys.stdout.buffer.write(plistlib.dumps({"Label": "addystack.coordinator-tick",
  "ProgramArguments": ["/bin/sh", sys.argv[1] + "/scripts/tick.sh"], "StartInterval": 600,
  "RunAtLoad": True, "StandardErrorPath": sys.argv[2] + "/Library/Logs/coordinator-tick.log"}))' \
  "$(pwd -P)" "$HOME" > ~/Library/LaunchAgents/addystack.coordinator-tick.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/addystack.coordinator-tick.plist
```

Linux, with lingering on (`loginctl enable-linger`) so it runs without a login:

```sh
mkdir -p ~/.config/systemd/user
printf '[Service]\nType=oneshot\nExecStart=/bin/sh %s/scripts/tick.sh\n' "$(pwd -P)" \
  > ~/.config/systemd/user/coordinator-tick.service
printf '[Timer]\nOnBootSec=2min\nOnUnitActiveSec=10min\n\n[Install]\nWantedBy=timers.target\n' \
  > ~/.config/systemd/user/coordinator-tick.timer
systemctl --user daemon-reload && systemctl --user enable --now coordinator-tick.timer
```

Errors go to `~/Library/Logs/coordinator-tick.log` on macOS and to
`journalctl --user -u coordinator-tick` on Linux.

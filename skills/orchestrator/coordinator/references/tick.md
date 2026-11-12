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
- **PR**: a PR on an open row (`running`, `waiting`, `overdue`, `unknown`, or `stuck`) or
  under Watches merged, closed, reopened, or turned ready or draft since the tick last
  saw it. The first look at a PR only records it.
- **Watch left on**: a PR under Watches that's merged or closed, even at the first look,
  since its watch should go.
- **Owner**: a `repo#N` whose owner the checkout's origin doesn't give. Every other form,
  `#N`, a range `#20–#22`, a URL, or `owner/repo#N`, resolves to one `owner/repo#N`.
- **Unreadable**: a live row whose cells don't match the Workers header, or that has no
  thread link.

Each finding except a PR change repeats hourly while it holds, so fixing the row or
Watches stops it.
While the coordinator's own thread runs, the tick still times its workers but sends
nothing and leaves PRs for later, so its turn settles first. `tick.json` beside
`project.md` holds what it last saw; a failed send leaves it unchanged, so the next tick
sends again. A thread or PR it can't read is named on stderr, in the timer's log.

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

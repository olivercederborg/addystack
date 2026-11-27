# Status page

An opt-in page of every coordinator project on this machine, which T3 Code shows as a tab
in its browser and which updates itself. It reads files only, so it never calls `t3` or
`gh`, and each card shows how old its data is.

## Opening it

On start or resume (SKILL.md step 1), run `<kit>/bin/addystack status-page`:

- **A URL**: the page is on and answering. Open it with `preview_open`, unless
  `t3_preview_list` already shows a tab at that URL.
- **Nothing**: the setting is off. Leave it there; the user turns it on.
- **Exit 1**: it's on but broken, and stderr says why. Tell the user in one line, with
  `addystack doctor`'s fix, and carry on with the project.

## The setting

`"coordinator": { "statusPage": true }` in `~/.config/addystack/addystack.jsonc`, then
`addystack install`, which writes the launchd agent `addystack.coordinator-status` and
starts it. Set it to `false` and install again to stop it and remove its plist. The
config is the user's: change it only when they ask. It runs on macOS only.

## What it shows

Every folder under `~/.local/state/orchestrate/` that holds a `project.md`, as
`project.snapshot` reads it: the Queue, each Workers row grouped by state, each live
row's thread status and each PR's state and draft from the tick's last look
(`tick.json`), and when each file last changed. Active projects come first, with the
most queue items first; parked and closed projects collapse to one line that still
shows their queue. A project.md it can't read, a Queue it can't read, or none at all
shows as unknown. Thread and PR states are as fresh as the tick: past 20 minutes, or
while the project's Heartbeat isn't `tick`, the card shows stale.

## The server

`scripts/status_server.py --port 47130` serves it on 127.0.0.1 only. `addystack install`
points launchd at the copy in the host's skill folder and restarts it when its sources
change.

| Request | Answer |
|---|---|
| `GET /` | `status.html`, which polls `/overview.json` every 2 s |
| `GET /overview.json` | every project's card, with an ETag; 304 while no `project.md`, `tick.json`, or the timer's `.tick` changed |
| any other path | 404 |
| a Host other than `localhost:47130` or `127.0.0.1:47130` | 403 |

Every reply carries `Server: addystack-coordinator-status`.

## When it's wrong

- **Doctor fails** its `status page` line: run the `fix:` it prints. `nothing answers`
  means the server exits at start; its log is
  `~/Library/Logs/addystack-coordinator-status.err.log`. `answers, but not as the status
  page` means another program holds port 47130.
- **A card is stale**: the tick timer isn't running, or the project's Heartbeat is
  `none`; see [tick](tick.md).
- **A card is unknown**: its reason names the file and what failed. Fix project.md with
  `scripts/project.py`.

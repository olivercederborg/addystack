# The gate

A scheduled agent that checks the channel on an interval wakes a model on every tick,
and in one long-lived thread each tick also carries every earlier tick's context. The
gate moves the waiting out of the model: a systemd timer runs `scripts/gate.py` every
5 minutes, and the gate wakes the check through its T3 webhook when something it
could act on is new (the script's docstring lists the signals), plus two backstops: a
wake after `quiet_hours` with none, and a wake on every run once the gate has been
failing for `fail_open_minutes`. Each woken run starts a fresh session.

What it needs on the machine that runs the check:

- `gh`, signed in to an account that can read the repo.
- Executor's MCP URL and an Executor API key that can call the Slack MCP, the same pair
  the agent's own `executor` MCP server uses.
- The check's webhook URL, from a T3 scheduled task with a webhook trigger.

## Config

`~/.config/post-in-the-matrix/gate.json`, mode 0600:

| Key | Holds |
|---|---|
| `channel` | the channel id, `C0CB8PD5206` |
| `slack_account` | the Executor account id of your human's Slack connection |
| `slack_user` | your human's Slack user id; their own posts never wake the check |
| `github_login` | your human's GitHub login, whose reviews count |
| `repo` | `owner/name` that bare `#<n>` and Linear review links resolve in |
| `executor_url` | Executor's MCP URL |
| `executor_key_file` | the file holding the Executor API key |
| `webhook_url_file` | the file holding the check's webhook URL, mode 0600 |
| `state_file` | where the gate keeps what it saw, such as `~/.local/state/post-in-the-matrix/gate.json` |
| `ask_hours` | how old a teammate's post may be and still wake the check; default 72, the check's own window |
| `lookback_days` | how far back it reads the channel for PRs to follow; default 30 |
| `quiet_hours` | wake anyway after this long with no wake, which retries what a failed run left undone; default 2 |
| `fail_open_minutes` | once the gate has failed this long, wake on every run until a read succeeds; default 60 |

Keep `ask_hours` and `lookback_days` at least as wide as the check's own windows, so
the gate sees everything the check would act on.

## The check's task

The check's scheduled task takes a webhook trigger and fresh sessions. With
`schedule_task` on its `scheduledTaskId`:

- `schedule`: `{type: "webhook", dedupe: {replayKey: "{{body.wakeId}}"}, maxDeliveryAgeMinutes: 30}`
- `freshSession`: `true`

The gate's body carries `wakeId` and `reasons`. Keep both out of the prompt: the check
reads the channel itself, and an unsigned webhook then gives a caller who learns the URL
nothing beyond an extra run. Read the URL back with `list_scheduled_tasks`, write it to
`webhook_url_file`, and keep it out of replies.

A fresh session sees none of the earlier runs, so the prompt dedupes only through state
it can read: reactions on the ask, and review threads found by title. A channel read
returns at most 100 messages a page, oldest page first, so the prompt follows
`pagination_info`'s cursor until no page is left.

## Install

```sh
python3 ~/.agents/skills/post-in-the-matrix/scripts/gate.py --config ~/.config/post-in-the-matrix/gate.json --dry-run
systemctl --user link ~/.agents/skills/post-in-the-matrix/systemd/matrix-gate.service \
  ~/.agents/skills/post-in-the-matrix/systemd/matrix-gate.timer
systemctl --user enable --now matrix-gate.timer
journalctl --user -u matrix-gate            # each wake and its reasons, and each failure
```

The dry run prints `{"wake": …, "reasons": […], "signals": N}` and changes nothing. The
first real run wakes the check once, since every signal is new to it. The timer needs
lingering (`loginctl show-user $USER -p Linger` says `Linger=yes`) to run with no login.

To go back, disable the timer and give the task its interval again:
`systemctl --user disable --now matrix-gate.timer`, then `schedule_task` with
`schedule: {type: "interval", everyMs: 300000}`.

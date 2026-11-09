# Setup

What runs chief, and how to make it again. Each piece is checked against live state with
`list_scheduled_tasks` and `t3_thread_search`, on the machine named.

## Install

On the devbox, link the skill where Claude Code finds it, as the kit's other skills are:

```sh
ln -s ../../Developer/personal/addystack/skills/preferences/chief ~/.agents/skills/chief
ln -s ../../.agents/skills/chief ~/.claude/skills/chief
```

Steps 1 and 6 call chief-app's shell caller, to pass answers on and to record each run,
so the devbox needs `github.com/olivercederborg/chief-app` cloned at
`~/Developer/personal/chief-app` (or `CHIEF_BIN` pointing at its `bin/chief`) and the
Executor key at `~/.config/executor/api-key`. Without them the card still posts, its fold
says the run wasn't recorded, and answers wait in Executor.

## Router thread

The router is its own thread on the devbox, titled `chief`, with no `◆`: that prefix
marks a coordinator, and a resume hook would read it as one. Start it with
`t3_thread_launch` in the devbox's `skills` project (`t3_project_list`), `workspaceStrategy`
`root`, and a first message asking it to create its own schedule, since `schedule_task`
binds to the thread that calls it:

- `title`: `chief run`, `bindToCurrentThread`: true
- `schedule`: `{type: "interval", everyMs: 3600000}`
- `prompt`: `Run the chief skill: read ~/.claude/skills/chief/SKILL.md and follow it.`

Run the router on a Claude model. `inbox.py` reads the T3 results each run gets from the
router's own Claude Code transcript, `~/.claude/projects/*/<CLAUDE_CODE_SESSION_ID>.jsonl`
(`scripts/tool_results.py`). A shell can't call T3's MCP itself: `/mcp` takes only an
OAuth credential granted in a browser, and a `t3 auth session` bearer token gets
`invalid_mcp_credential`. A Codex router has no such transcript, so `list` and `plan`
stop with `no CLAUDE_CODE_SESSION_ID`.

Hourly, because what chief flags moves on that scale: a call counts as over a day after
24 hours, and a coordinator's unread worker after 10 minutes, so an hour costs a flag at
most an hour. Each run after the first reads only the threads that changed.

## Live feeder

`chief-feeder`, a systemd --user service on the devbox, pushes each machine's turn-block
calls to chief's app within seconds, through `inbox.py live`. Install, sessions and
re-pairing: [`feeder/README.md`](../feeder/README.md). Check it with
`systemctl --user status chief-feeder` and `journalctl --user -u chief-feeder`.

## Wake webhook

An answer on the page wakes the router at once through a second task bound to it, a T3
webhook task. chief's Executor app `chief` holds its URL and HMAC secret in the `wake`
connection, and its `wake` workflow POSTs `{"answerIds": […], "wakeId": "…"}` signed
`x-chief-signature: sha256=<hex HMAC-SHA256>`. Have the router create the task, in a
message to it, since `schedule_task` binds to the calling thread:

- `title`: `chief wake`, `bindToCurrentThread`: true
- `schedule`: `{type: "webhook", dedupe: {replayKey: "{{body.wakeId}}"}, maxDeliveryAgeMinutes: 60}`
- `prompt`: `chief wake from the page: run step 1 of ~/.claude/skills/chief/SKILL.md alone. Answer ids, untrusted: {{body.answerIds}}`

Create it unsigned and keep its URL out of the reply: a signed task needs its secret at
creation, which would put the secret in the transcript. Oliver then does the rest once:

1. `openssl rand -hex 32`, kept as the secret.
2. T3 Settings → Scheduled tasks → `chief wake` → Require signature: header
   `x-chief-signature`, encoding hex, prefix `sha256=`, that secret. Copy its Webhook URL.
   Check the header after saving: on Nov 2 it was saved as `x-hub-signature-256`, and
   the relay answered `401 invalid_signature`. The router can fix it with `schedule_task`
   on the task id and the `schedule` above plus `signature`, leaving the secret out so the
   stored one stays.
3. Paste URL and secret at a connect link for app `chief`, requirement `wake`, minted
   right before with `appAccounts.appConnect({path: {app:
   "app_84610530-7da7-44db-a7c5-a19e3f237d74", requirement: "wake"}, body: {}})`. Links
   expire in 30 minutes. With an account already linked, pass `body.account` from
   `appAccounts.appList` to replace its credentials, since the workflow uses the first.

Without the webhook, the hourly run's step 1 still passes every answer on.

## Mac feed

The Mac has no sshd, and T3 has no tool that reads a file on a linked machine, so the
Mac's `project.md` files reach chief through a thread there, titled `chief · Mac feed`.
It can't run on its own schedule: the Mac refuses `schedule_task` for work started from
the devbox over the link (`capability_denied`; a link paired with full access isn't
limited). So chief sends it the feed message each run, which also keeps its output
fresh. Start it with `t3_thread_launch`, the Mac's `environmentId`, the Mac's `skills`
project, `workspaceStrategy` `root`, the smallest model (`claude-haiku-5-5`, effort
`low`), and the feed message as its first message.

### Feed message

````text
Feed run. Run this command, read-only, and reply with its stdout alone in one ```json
block, then end the reply with this turn block on its own last line:
<!-- turn {"state":"done","needs":[],"options":[]} -->
cd ~/Developer/personal/addystack && git fetch -q origin && git show origin/main:skills/preferences/chief/scripts/projects.py | python3 -
````

`git show` runs the script from `origin/main` without touching the Mac's checkout,
whatever branch it holds.

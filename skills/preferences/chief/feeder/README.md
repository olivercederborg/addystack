# chief's live feeder

An always-on devbox process (D16). It holds one WebSocket to each T3 server, mirrors its
shell from `orchestration.subscribeShell`, reads a thread's projection when its run key
(`latestRunId|status|activityRunStatus|pendingRequest kind`) moves, and pushes the calls
the turn blocks make to chief's Executor app with `record_live`, about 5 s after a change.
The page then shows a new need, or drops a cleared one, within seconds instead of on the
hour. The hourly chief run still owns flags, PR rows and the Mac's project.md feed.

```
feeder.mjs            the process: sockets, reads, pushes, health
shell.mjs             its pure parts: the shell mirror, run key, what to read, health rows
shell.test.mjs        their tests (node --test; test_chief.py runs them too)
chief-feeder.service  the systemd --user unit
```

**One rule source.** The feeder decides nothing about needs. It hands each machine's
listed threads, with their shell fields and projection details, to
`python3 chief/scripts/inbox.py live`, the rules the hourly card uses, and pushes what it
returns. A reply with no turn block makes no call.

What it pushes, per machine, as the feed run `feed_<machine>` (chief-app README, Live feed):

- the calls on its unsettled, awake, non-subagent threads, ranked as the card ranks them;
- **The live feed can't reach <machine>**, once its socket has been down 10 minutes;
- **Re-pair <machine>**, from 3 days before its session's `expiresAt`, or as soon as the
  server refuses the session.

It re-pushes unchanged rows every 5 minutes. chief-app ignores a feed not pushed for 15
minutes, so a stopped feeder falls back to the hourly run's rows. A drop under 10 minutes
pushes nothing, and the last push stands.

## Sessions

One bearer session per server, scope `orchestration:read` only, in a 0600 file the feeder
re-reads on every connect, so a re-paired session needs no restart:

| Machine | File | Holds |
|---|---|---|
| devbox | `~/.config/chief/devbox-session.json` | `token`, `expiresAt` (origin `http://127.0.0.1:3773`) |
| Mac | `~/.config/chief/mac-session.json` | `token`, `expiresAt`, `origin` (its T3 Connect relay), `environmentId` |

A session lasts 30 days, with no refresh. When the page shows **Re-pair**:

- **devbox:** `t3 auth session issue --scope orchestration:read --ttl 30d --label chief-feeder --json > ~/.config/chief/devbox-session.json`
  (keep it 0600), then revoke the old one in Settings → Connections.
- **Mac:** on the Mac, `t3 auth pairing create --scope orchestration:read --ttl 15m --label chief-feeder --json`.
  Give its 12-character `credential` to an agent on the devbox through `request_secret`, never
  chat. The agent exchanges it at `POST <relay>/oauth/token` (grant type
  `urn:ietf:params:oauth:grant-type:token-exchange`, subject token type
  `urn:t3:params:oauth:token-type:environment-bootstrap`) and writes the result, with
  `origin`, `environmentId` and `expiresAt`, to `mac-session.json`.

The feeder never logs a token.

## Install

On the devbox, with lingering on so it runs with no login (`loginctl show-user $USER -p Linger`
says `Linger=yes`; else `sudo loginctl enable-linger $USER`):

```sh
systemctl --user link ~/Developer/personal/addystack/skills/preferences/chief/feeder/chief-feeder.service
systemctl --user enable --now chief-feeder
journalctl --user -u chief-feeder -f        # snapshots, reconnects, and each push that changed
```

`CHIEF_FEEDER_DRY=1 node chief/feeder/feeder.mjs` prints each push instead of sending it.
`CHIEF_FEEDER_SESSIONS` takes a comma-separated list of session files, each optionally
`file=origin`, to run against one server or a proxy.

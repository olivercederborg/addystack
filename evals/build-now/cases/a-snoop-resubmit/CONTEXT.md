# Replay: a Snoop recording stuck on "still taking notes" (T3 fb5acb38, 2026-10-28)

Repo: snoop, Oliver's own app. The server is a Cloudflare Worker: each recording runs as a
Workflow that sends the audio to ElevenLabs for transcription, then waits for ElevenLabs'
webhook. A run gives up after a 1-hour wait.

Oliver sent a screenshot from Nikolaj (a pilot user): his recording sat on "still taking
notes" and never finished. You've investigated and built a fix. This is the end of that run:
report back.

## What you found

- **Recording** `1b96a6a6`, 330 s, uploaded 08:46:23 UTC. The run sent it to ElevenLabs at
  08:46:30, then waited for the webhook.
- **ElevenLabs**: the production webhook's last failure was HTTP 400 at 08:46:34. No other
  recording was in flight. Our webhook answers 400 only to a body it can't decode.
- **Not the audio**: the file is intact. Sent again to ElevenLabs (with production's key, a
  few cents, nothing printed), it transcribes in 62 s with every word timed.
- **So**: 4 s is too soon for a transcript. It was ElevenLabs' `webhook_error` event (no
  `data` object, per their docs), which our webhook didn't model. This is inferred: the 400'd
  body was never logged. Most likely a transient failure at ElevenLabs.
- The recording turned failed at 09:46 when the hour ran out, so **Try Again** now reruns it.

## Draft PR #132 (own repo, no CI, not deployed, no reviews)

| # | Item | Status |
|---|---|---|
| 1 | `webhook_error` fails the recording at once and wakes its run | ✅ `ec5d40a` |
| 2 | Words without timestamps join the turn before them | ✅ `57d4849` |
| 3 | An unreadable delivery logs its type and keys | ✅ `53e5369` |
| 4 | README | ✅ |
| 5 | An empty error message stores `elevenlabs: ` with nothing after it | open |
| 6 | The 500 log still says "Storing a transcript failed" for a failure | open |
| 7 | Resubmit automatically on a transient ElevenLabs failure, so a blip like today's never reaches the user | open |
| 8 | A late failure from a first attempt could fail a rerun. ElevenLabs sends a failure once and only retries on our 5xx, which this path doesn't return | open |

With #132 as it stands, a failure like Nikolaj's turns the recording failed within seconds
and shows Try Again, instead of hanging for an hour. The user still has to tap Try Again.

Checks: `pnpm check` passes; the new tests fail on main and pass here; Codex review round 1
came back Clean; verify-work couldn't see a real `webhook_error` delivery (needs a deploy).

A Slack reply to Nikolaj, in Danish, is drafted for Oliver to post.

## The thread

Oliver: "investigate this [screenshot: Nikolaj's recording on 'still taking notes']"

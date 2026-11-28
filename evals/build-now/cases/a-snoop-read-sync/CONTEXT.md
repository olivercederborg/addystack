# Replay: read state in Snoop's cross-device plan (T3 8f91d657, 2026-10-18 21:15)

Repo: snoop, Oliver's own app (an iPhone app, a Mac app, shared SnoopKit, and a server).
Users record meetings ("snoops"); the server transcribes and summarizes them. Nothing here
is released to anyone but Oliver's pilot (his iPhone and Mac).

## The plan in progress (scope-grill for milestone 3.8, cross-device snoops)

Nothing is built or saved yet. The Mac stack (#38–#44, #51) is merged.

**Goal**: each app lists all your snoops from every device, and opens their notes and
transcript.

**What the code says**

- **Server**: `GET /v1/recordings` already returns every snoop of the signed-in member, from
  every device (`server/src/recordings/recording.repository.d1.ts:167`).
- **Audio**: the server deletes a snoop's audio once it's ready, so only the recording device
  can play it.
- **Apps**: today each app lists only `Recorder.recordings`, the snoops on its own disk.
  This milestone makes both apps list every snoop from the server.
- **Unread**: the blue unread dot comes from OpenedLedger, a file on each device. A snoop
  gets the dot once its notes are ready and loses it the first time you open it on that
  device.

**Oliver's model** (his words, 21:04): "I think it should probably work such that snoop is
local first and syncs to and from the server, but once it's on the server, any device should
be able to modify or delete records".

**Settled so far**

- Delete: any device can delete a snoop once it's on the server (Oliver).
- Offline: other devices' snoops stay in the list from the last fetch.
- Rename and tags: belong to the separate "Snoop Renaming and Custom Tags" thread
  (milestone 3.7, mid-build), and work on any snoop by its ID.
- Order: this lands after 3.7 merges.

**Still open**

- **Q4**: when a snoop is deleted on another device, is the recording device's audio deleted
  too? (A: deleted too, ≈4 files, hard to undo. B: kept as a local-only copy, ≈5 files.)
- **Q2**: read on one device, read on both?
  - A · Per device, as today: no extra scope, easy to undo.
  - B · Synced through the server: adds an "opened" field on the server, a route to set it,
    and a migration, plus a client call · ≈8 files · hard to undo: migration.

## The thread

Your last message asked Oliver to decide Q4 and Q2.

Oliver: "What does read state per device mean?"

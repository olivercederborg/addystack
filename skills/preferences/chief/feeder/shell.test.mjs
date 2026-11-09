// Tests for shell.mjs: `node --test skills/preferences/chief/feeder/shell.test.mjs` (test_chief.py runs them too).
import assert from "node:assert/strict";
import { test } from "node:test";
import { detailsOf, feedThread, healthNeeds, listed, readsDue, runKey, ShellMirror, wantsRead } from "./shell.mjs";

const NOW = Date.parse("2026-11-03T12:00:00Z");
const ago = (minutes) => new Date(NOW - minutes * 60_000).toISOString();

const thread = (id, fields = {}) => ({
  id,
  title: `Thread ${id}`,
  createdBy: "user",
  status: "completed",
  latestRunId: `run:${id}:1`,
  activityRunStatus: null,
  pendingRuntimeRequest: null,
  latestRunStartedAt: ago(30),
  latestRunCompletedAt: ago(20),
  updatedAt: ago(20),
  archivedAt: null,
  deletedAt: null,
  settledOverride: null,
  settledAt: null,
  snoozedUntil: null,
  lineage: { parentThreadId: null, relationshipToParent: null },
  pullRequests: [],
  ...fields,
});
const snapshot = (sequence, threads, extra = {}) => ({
  kind: "snapshot",
  snapshot: { snapshotSequence: sequence, threads, projects: [] },
  ...extra,
});
const updated = (sequence, value, location = "active") => ({ kind: "thread.updated", sequence, location, thread: value });

test("the mirror holds the snapshot and applies only later events", () => {
  const mirror = new ShellMirror();
  assert.equal(mirror.apply(updated(5, thread("early"))), null, "an event before any snapshot waits");
  assert.deepEqual([...mirror.apply(snapshot(10, [thread("a"), thread("b")]))].sort(), ["a", "b"]);
  assert.equal(mirror.apply(updated(10, thread("a", { title: "old" }))), null, "at the snapshot's sequence: in it already");
  assert.deepEqual([...mirror.apply(updated(11, thread("a", { title: "new" })))], ["a"]);
  assert.equal(mirror.threads.get("a").title, "new");
  assert.equal(mirror.apply(updated(11, thread("a", { title: "replayed" }))), null);
  // A thread that leaves the active list (archived, settled away) drops off.
  assert.deepEqual([...mirror.apply(updated(12, thread("b"), "archived"))], ["b"]);
  assert.deepEqual([...mirror.apply({ kind: "thread.removed", sequence: 13, location: "active", threadId: "a" })], ["a"]);
  assert.equal(mirror.threads.size, 0);
});

test("enrichment and empty snapshots never wipe a full one", () => {
  const mirror = new ShellMirror();
  mirror.apply(snapshot(10, [thread("a")]));
  assert.equal(mirror.apply(snapshot(10, [], { resolvedRepositoryIdentityRoots: [] })), null);
  assert.equal(mirror.apply(snapshot(11, [])), null);
  assert.deepEqual([...mirror.threads.keys()], ["a"]);
});

test("a new socket waits for its own snapshot, which replaces the threads", () => {
  const mirror = new ShellMirror();
  mirror.apply(snapshot(10, [thread("a"), thread("gone")]));
  mirror.awaitSnapshot();
  assert.equal(mirror.apply(updated(20, thread("a"))), null, "events wait for the new snapshot");
  assert.deepEqual([...mirror.apply(snapshot(30, [thread("a")]))].sort(), ["a", "gone"]);
  assert.deepEqual([...mirror.threads.keys()], ["a"]);
  assert.equal(mirror.sequence, 30);
});

test("the run key moves with a new run, its end, or a request, and nothing else", () => {
  const base = thread("a");
  const key = runKey(base);
  assert.equal(runKey({ ...base, title: "renamed", updatedAt: ago(1), lastVisitedAt: ago(1) }), key);
  assert.notEqual(runKey({ ...base, latestRunId: "run:a:2" }), key);
  assert.notEqual(runKey({ ...base, status: "running", activityRunStatus: "running" }), key);
  assert.notEqual(runKey({ ...base, pendingRuntimeRequest: { kind: "question" } }), key);
});

test("a projection is read on a run key change, once while at work, and never asleep or settled", () => {
  const idle = thread("a");
  const read = { key: runKey(idle) };
  assert.equal(wantsRead(idle, undefined, NOW), true, "never read");
  assert.equal(wantsRead(idle, read, NOW), false, "nothing moved");
  assert.equal(wantsRead({ ...idle, title: "renamed" }, read, NOW), false);
  const next = { ...idle, latestRunId: "run:a:2" };
  assert.equal(wantsRead(next, read, NOW), true, "its run ended again");
  const busy = { ...idle, status: "running", latestRunId: "run:a:2" };
  assert.equal(wantsRead(busy, undefined, NOW), true, "read once for its first message");
  assert.equal(wantsRead(busy, read, NOW), false, "its reply counts again when the run ends");
  assert.equal(wantsRead({ ...next, snoozedUntil: ago(-60) }, read, NOW), false);
  assert.equal(wantsRead({ ...next, snoozedUntil: ago(60) }, read, NOW), true, "a snooze that ran out");
  assert.equal(wantsRead({ ...next, settledAt: ago(5) }, read, NOW), false);
  assert.equal(wantsRead({ ...next, settledAt: ago(5), settledOverride: "unsettled" }, read, NOW), true);
  assert.equal(wantsRead({ ...next, archivedAt: ago(5) }, read, NOW), false);
});

test("subagents, settled and archived threads aren't listed", () => {
  assert.equal(listed(thread("a")), true);
  assert.equal(listed(thread("a", { lineage: { relationshipToParent: "subagent" } })), false);
  assert.equal(listed(thread("a", { lineage: { relationshipToParent: "fork" } })), true);
  assert.equal(listed(thread("a", { settledOverride: "settled" })), false);
  assert.equal(listed(thread("a", { archivedAt: ago(1) })), false);
});

const message = (id, role, minutes, text = "", extra = {}) => ({
  id,
  role,
  text,
  createdAt: ago(minutes),
  updatedAt: ago(minutes),
  ...extra,
});

test("details keep the newest finished reply, the first message, and a later user message", () => {
  const projection = {
    messages: [
      message("u1", "user", 40, "Worker of: t3-thread://v2/env/coord\n\nDo it."),
      message("r1", "assistant", 35, "old reply"),
      message("r2", "assistant", 25, "Done.\n\n<!-- turn {} -->"),
      message("r3", "assistant", 1, "half wri", { streaming: true }),
      message("u2", "user", 10, "and another thing"),
    ],
  };
  const details = detailsOf(projection, thread("a", { status: "running" }));
  assert.equal(details.reply.text, "Done.\n\n<!-- turn {} -->");
  assert.equal(details.first, "Worker of: t3-thread://v2/env/coord\n\nDo it.");
  assert.equal(details.lastUserAt, ago(10));
  assert.equal(details.key, runKey(thread("a", { status: "running" })));
});

test("a reply that predates the run, or still streams, isn't settled, so the feeder reads again", () => {
  const ran = thread("a", { latestRunStartedAt: ago(10) });
  const before = { messages: [message("u", "user", 30), message("r", "assistant", 20, "earlier run")] };
  assert.equal(detailsOf(before, ran).settledReply, false);
  const streaming = { messages: [message("r", "assistant", 5, "par", { streaming: true })] };
  assert.equal(detailsOf(streaming, ran).settledReply, false);
  const done = { messages: [message("r", "assistant", 5, "Done.")] };
  assert.equal(detailsOf(done, ran).settledReply, true);
});

test("a thread with no reply or no block goes to inbox.py as it is", () => {
  const details = detailsOf({ messages: [message("u", "user", 5, "hi")] }, thread("a", { latestRunStartedAt: null }));
  assert.equal(details.reply, null);
  const item = feedThread("env", thread("a", { pendingRuntimeRequest: { kind: "approval" } }), details, NOW);
  assert.deepEqual(item.details, { reply: null, first: "hi", lastUserAt: ago(5) });
  assert.equal(item.pending, 1);
  assert.equal("details" in feedThread("env", thread("b"), undefined, NOW), false, "unread: shell only");
});

test("only open PRs ride along", () => {
  const pullRequests = [
    { repository: "o/r", number: 1, snapshot: { state: "open" } },
    { repository: "o/r", number: 2, snapshot: { state: "merged" } },
  ];
  assert.deepEqual(feedThread("env", thread("a", { pullRequests }), undefined, NOW).prs, [
    { repo: "o/r", number: 1, state: "open" },
  ]);
});

test("health rows: down for 10 minutes, and re-pair from 3 days before the session ends", () => {
  const base = { machine: "Mac", downSince: null, lastError: null, expiresAt: ago(-60 * 24 * 10), refusedAt: null, link: "README" };
  assert.deepEqual(healthNeeds(base, NOW), []);
  assert.deepEqual(healthNeeds({ ...base, downSince: NOW - 9 * 60_000 }, NOW), []);
  const [down] = healthNeeds({ ...base, downSince: NOW - 10 * 60_000, lastError: "socket closed (1006)" }, NOW);
  assert.equal(down.objectId, "chief-feeder:Mac/socket");
  assert.equal(down.what, "The live feed can't reach Mac since 11:50 UTC: socket closed (1006)");
  const ends = NOW + 2 * 24 * 3_600_000;
  const [repair] = healthNeeds({ ...base, expiresAt: new Date(ends).toISOString() }, NOW);
  assert.equal(repair.objectId, "chief-feeder:Mac/session");
  assert.equal(repair.since, new Date(ends - 3 * 24 * 3_600_000).toISOString().replace(".000", ""));
  const [refused] = healthNeeds({ ...base, refusedAt: NOW - 1000 }, NOW);
  assert.equal(refused.what, "Re-pair Mac for the live feed: its session was refused");
  // Rows hold still between pushes, so an unchanged state isn't pushed again.
  assert.deepEqual(healthNeeds({ ...base, refusedAt: NOW - 1000 }, NOW + 60_000), [refused]);
});

test("a thread whose snooze runs out is due on the next tick, with no shell event", () => {
  const mirror = new ShellMirror();
  mirror.apply(snapshot(1, [thread("asleep", { snoozedUntil: ago(-5) }), thread("read")]));
  const details = new Map([["read", { key: runKey(thread("read")) }]]);
  assert.deepEqual(readsDue(mirror, details, NOW), []);
  assert.deepEqual(readsDue(mirror, details, NOW + 6 * 60_000), ["asleep"]);
});

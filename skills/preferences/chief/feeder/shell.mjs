// The feeder's pure parts: one server's shell mirror, when a thread's projection is worth
// reading, what to keep from it, and the feeder's own health rows. No I/O, so tests drive it.
//
// It ports Prefrontal's ShellMirror.swift and Details.swift (olivercederborg/prefrontal,
// Sources/PrefrontalKit/T3/). Which threads make a call, and what it says, is not here:
// chief/scripts/inbox.py `live` holds those rules, as it does for the hourly card.

/** Run states that mean the thread is at work, as inbox.py's ACTIVE. */
export const ACTIVE = new Set(["queued", "preparing", "starting", "running", "waiting"]);

/**
 * One server's shell, kept current from `orchestration.subscribeShell` items. A new socket
 * calls awaitSnapshot; events wait for its first full snapshot, and events at or before the
 * snapshot's sequence are already in it.
 */
export class ShellMirror {
  threads = new Map();
  sequence = -1;
  hasSnapshot = false;

  /** Applies one item; returns the ids of threads it changed, or null when it changed nothing. */
  apply(item) {
    switch (item?.kind) {
      case "snapshot": {
        // An enrichment snapshot refreshes repository identities only; its lists are empty.
        if ("resolvedRepositoryIdentityRoots" in item && this.hasSnapshot) return null;
        const snapshot = item.snapshot ?? {};
        // An empty list once a full snapshot is held is an enrichment that lacks the marker.
        if (this.hasSnapshot && !(snapshot.threads ?? []).length) return null;
        const changed = new Set(this.threads.keys());
        this.threads = new Map();
        for (const thread of snapshot.threads ?? []) {
          if (thread.deletedAt) continue;
          this.threads.set(thread.id, thread);
          changed.add(thread.id);
        }
        this.sequence = snapshot.snapshotSequence ?? -1;
        this.hasSnapshot = true;
        return changed;
      }
      case "thread.updated": {
        if (!this.#advance(item.sequence)) return null;
        const thread = item.thread;
        if (item.location !== "active" || !thread || thread.deletedAt)
          return this.threads.delete(thread?.id) ? new Set([thread.id]) : null;
        this.threads.set(thread.id, thread);
        return new Set([thread.id]);
      }
      case "thread.removed": {
        if (!this.#advance(item.sequence) || item.location !== "active") return null;
        return this.threads.delete(item.threadId) ? new Set([item.threadId]) : null;
      }
      case "project.updated":
      case "project.removed":
        this.#advance(item.sequence);
        return null;
      default:
        return null;
    }
  }

  awaitSnapshot() {
    this.hasSnapshot = false;
    this.sequence = -1;
  }

  #advance(next) {
    if (!this.hasSnapshot || !(next > this.sequence)) return false;
    this.sequence = next;
    return true;
  }
}

/** What changes whenever a thread's reply may have: a new run, a run ending, a request opening or closing. */
export const runKey = (thread) =>
  [thread.latestRunId ?? "", thread.status ?? "", thread.activityRunStatus ?? "", thread.pendingRuntimeRequest?.kind ?? ""].join(
    "|",
  );

export const settled = (thread) =>
  thread.settledOverride === "settled" || (thread.settledOverride == null && thread.settledAt != null);

export const snoozed = (thread, now) => thread.snoozedUntil != null && Date.parse(thread.snoozedUntil) > now;

/**
 * The threads chief's card reads, as its t3_thread_list call lists them: not archived, not
 * settled, not a subagent. A snoozed one stays listed, flagged, and inbox.py drops it.
 */
export const listed = (thread) =>
  !thread.archivedAt && !thread.deletedAt && !settled(thread) && thread.lineage?.relationshipToParent !== "subagent";

/**
 * Whether to read a thread's projection now: listed, awake, and its run key moved since the
 * last read. A thread at work is read once, for its first message; after that its reply
 * matters again only when the run ends, which moves the key.
 */
export function wantsRead(thread, details, now) {
  if (!listed(thread) || snoozed(thread, now)) return false;
  if (!details) return true;
  return details.key !== runKey(thread) && !ACTIVE.has(thread.status);
}

/**
 * The threads whose projection is due now. The feeder asks on every tick as well as on
 * each shell event, since T3 sends no event when a snooze runs out.
 */
export const readsDue = (mirror, details, now) =>
  [...mirror.threads.values()].filter((thread) => wantsRead(thread, details.get(thread.id), now)).map((thread) => thread.id);

const byTime = (a, b) =>
  a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;

/**
 * What the feeder keeps from `orchestration.getThreadProjection`: the newest finished
 * assistant reply, the first user message (whose `Worker of:` line names a coordinator), and
 * the latest user message after the reply. `settledReply` is false when the run's reply isn't
 * in yet, so the feeder reads again shortly.
 */
export function detailsOf(projection, thread) {
  const messages = projection?.messages ?? [];
  const replies = messages.filter((message) => message.role === "assistant").sort(byTime);
  const reply = replies.filter((message) => message.streaming !== true).at(-1);
  const users = messages.filter((message) => message.role === "user").sort(byTime);
  const after = reply ? users.filter((message) => byTime(message, reply) > 0) : users;
  const started = thread.latestRunStartedAt ?? "";
  return {
    key: runKey(thread),
    reply: reply ? { text: reply.text ?? "", at: reply.updatedAt ?? reply.createdAt } : null,
    first: users[0] ? String(users[0].text ?? "").slice(0, 4000) : null,
    lastUserAt: after.length ? after.map((message) => message.updatedAt ?? message.createdAt).sort().at(-1) : null,
    settledReply:
      ACTIVE.has(thread.status) ||
      replies.at(-1)?.streaming !== true && (!started || (reply !== undefined && reply.createdAt >= started)),
  };
}

/** One thread as `inbox.py live` takes it: its shell's fields, and its details once read. */
export function feedThread(env, thread, details, now) {
  return {
    env,
    id: thread.id,
    title: thread.title,
    status: thread.status,
    createdBy: thread.createdBy,
    updatedAt: thread.updatedAt,
    snoozed: snoozed(thread, now),
    prs: (thread.pullRequests ?? [])
      .filter((pr) => pr.snapshot?.state === "open")
      .map((pr) => ({ repo: pr.repository, number: pr.number, state: "open" })),
    pending: thread.pendingRuntimeRequest ? 1 : 0,
    runCompletedAt: thread.latestRunCompletedAt,
    ...(details ? { details: { reply: details.reply, first: details.first, lastUserAt: details.lastUserAt } } : {}),
  };
}

export const DOWN_AFTER = 10 * 60_000;
export const REPAIR_BEFORE = 3 * 24 * 3_600_000;

const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

/**
 * The feeder's own rows for one machine: its socket down for 10 minutes, and its session
 * ending within 3 days or refused (refusedAt, ms). `link` is where the fix is written down.
 */
export function healthNeeds({ machine, downSince, lastError, expiresAt, refusedAt, link }, now) {
  const needs = [];
  const base = { kind: "do", title: `chief feeder · ${machine}`, pr: false, machine, holds: 1, url: link };
  if (downSince !== null && now - downSince >= DOWN_AFTER)
    needs.push({
      ...base,
      objectId: `chief-feeder:${machine}/socket`,
      what: `The live feed can't reach ${machine} since ${iso(downSince).slice(11, 16)} UTC${lastError ? `: ${lastError}` : ""}`.slice(0, 200),
      since: iso(downSince),
    });
  const ends = Date.parse(expiresAt ?? "");
  if (refusedAt != null || (Number.isFinite(ends) && ends - now <= REPAIR_BEFORE))
    needs.push({
      ...base,
      objectId: `chief-feeder:${machine}/session`,
      what: refusedAt != null
        ? `Re-pair ${machine} for the live feed: its session was refused`
        : `Re-pair ${machine} for the live feed: its session ends ${iso(ends).slice(0, 16).replace("T", " ")} UTC`,
      since: iso(refusedAt ?? Math.min(now, ends - REPAIR_BEFORE)),
    });
  return needs;
}

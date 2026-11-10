#!/usr/bin/env node
// chief's live feeder (D16): holds one WebSocket to each T3 server, mirrors its shell from
// `orchestration.subscribeShell`, reads a thread's projection when its run key moves, and
// within seconds pushes the calls the threads' turn blocks make to chief's Executor app
// (`record_live`). Which threads make a call, and what it says, comes from
// `chief/scripts/inbox.py live`, the rules the hourly card uses.
//
//   node skills/preferences/chief/feeder/feeder.mjs   run until stopped (systemd: chief-feeder.service)
//
// Env:
//   CHIEF_FEEDER_SESSIONS  comma-separated session files, each optionally `file=origin`
//                          (default ~/.config/chief/devbox-session.json,
//                          ~/.config/chief/mac-session.json)
//   CHIEF_FEEDER_DRY=1     print each push instead of sending it
//   CHIEF_BIN              chief-app's bin/chief (default ~/Developer/personal/chief-app/bin/chief)
//
// A session file holds a bearer `token` with scope orchestration:read, its `expiresAt`, and
// for a remote server its `origin` and `environmentId`. It is re-read on every connect, so a
// re-pair needs no restart. Tokens never reach the log.
import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { detailsOf, DOWN_AFTER, feedThread, healthNeeds, listed, readsDue, ShellMirror, wantsRead } from "./shell.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const INBOX = join(HERE, "..", "scripts", "inbox.py");
const home = (path) => path.replace(/^~(?=\/)/, homedir());
const CHIEF_BIN = home(process.env.CHIEF_BIN ?? "~/Developer/personal/chief-app/bin/chief");
const DRY = process.env.CHIEF_FEEDER_DRY === "1";
const README = "https://github.com/olivercederborg/addystack/blob/main/skills/preferences/chief/feeder/README.md";
const LOCAL_ORIGIN = "http://127.0.0.1:3773";
const SUBSCRIBE = { omitOlderSettled: true, omitIdleSubagents: true };

const PUSH_AFTER = 5_000; // gather a burst of changes into one push
const HEARTBEAT = 5 * 60_000; // re-push unchanged rows, so the app knows the feed is alive
const TICK = 30_000;
const PING = 15_000;
const SILENT = 45_000; // no frame for this long: the socket is dead even if it never closed
const BACKOFF = [1_000, 30_000];
const REFUSED_RETRY = 5 * 60_000;
const READS = 3; // projection reads in flight per server
const REPLY_RETRIES = 3;

const log = (...parts) => console.log(parts.join(" "));
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

function run(command, args, input) {
  return new Promise((resolve, reject) => {
    const child = execFile(command, args, { maxBuffer: 16 * 1024 * 1024, timeout: 90_000 }, (error, stdout, stderr) =>
      error ? reject(new Error(`${String(stderr || error.message).trim().split("\n").at(-1)}`)) : resolve(stdout),
    );
    child.stdin.end(input);
  });
}

class Machine {
  mirror = new ShellMirror();
  details = new Map();
  retries = new Map();
  queue = [];
  reading = new Set();
  calls = new Map();
  nextId = 2;
  ws = null;
  generation = 0;
  backoff = BACKOFF[0];
  downSince = Date.now();
  lastError = null;
  refusedAt = null;
  lastFrameAt = 0;
  lastPushed = null;
  lastPushAt = 0;
  pushTimer = null;
  pushing = false;
  name = null;
  connected = false;

  constructor(file, origin) {
    this.file = file;
    this.originOverride = origin;
    this.label = file.split("/").at(-1).replace(/-session\.json$/, "");
  }

  session() {
    const session = JSON.parse(readFileSync(this.file, "utf8"));
    return {
      token: session.token ?? session.access_token,
      origin: this.originOverride ?? session.origin ?? LOCAL_ORIGIN,
      environmentId: session.environmentId,
      expiresAt: session.expiresAt,
    };
  }

  async connect() {
    const generation = ++this.generation;
    let session;
    try {
      session = this.session();
      this.expiresAt = session.expiresAt;
      if (!this.env) {
        this.env =
          session.environmentId ??
          (await (await fetch(new URL("/.well-known/t3/environment", session.origin), { signal: AbortSignal.timeout(SILENT) })).json())
            .environmentId;
      }
      const ticket = await fetch(new URL("/api/auth/websocket-ticket", session.origin), {
        method: "POST",
        headers: { authorization: `Bearer ${session.token}` },
        signal: AbortSignal.timeout(SILENT),
      });
      if (ticket.status === 401 || ticket.status === 403) {
        this.refusedAt ??= Date.now();
        return this.fail(generation, `session refused (HTTP ${ticket.status})`, REFUSED_RETRY);
      }
      if (!ticket.ok) return this.fail(generation, `ticket HTTP ${ticket.status}`);
      this.refusedAt = null;
      const url = new URL("/ws", session.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.searchParams.set("orchestrationProtocol", "2");
      url.searchParams.set("wsTicket", (await ticket.json()).ticket);
      this.open(new WebSocket(url), generation);
    } catch (error) {
      this.fail(generation, error.cause?.code ?? error.message);
    }
  }

  open(ws, generation) {
    this.ws = ws;
    this.lastFrameAt = Date.now();
    this.mirror.awaitSnapshot();
    ws.addEventListener("open", () => {
      if (generation !== this.generation) return;
      ws.send(JSON.stringify({ _tag: "Request", id: "1", tag: "orchestration.subscribeShell", payload: SUBSCRIBE, headers: [] }));
    });
    ws.addEventListener("message", async (event) => {
      if (generation !== this.generation) return;
      this.lastFrameAt = Date.now();
      const text = typeof event.data === "string" ? event.data : Buffer.from(await event.data.arrayBuffer()).toString("utf8");
      let frame;
      try {
        frame = JSON.parse(text);
      } catch {
        return;
      }
      if (frame._tag === "Chunk") {
        ws.send(JSON.stringify({ _tag: "Ack", requestId: String(frame.requestId) }));
        if (String(frame.requestId) === "1") for (const item of frame.values ?? []) this.apply(item);
      } else if (frame._tag === "Exit") {
        const id = String(frame.requestId);
        if (id === "1") return this.fail(generation, `subscription ended: ${JSON.stringify(frame.exit).slice(0, 160)}`);
        const call = this.calls.get(id);
        this.calls.delete(id);
        if (!call) return;
        if (frame.exit?._tag === "Success") call.resolve(frame.exit.value);
        else call.reject(new Error(JSON.stringify(frame.exit).slice(0, 200)));
      } else if (frame._tag === "Defect") {
        this.fail(generation, `defect: ${text.slice(0, 160)}`);
      }
    });
    ws.addEventListener("close", (event) => this.fail(generation, `socket closed (${event.code})`));
    ws.addEventListener("error", (event) => this.fail(generation, `socket error${event.message ? `: ${event.message}` : ""}`));
  }

  apply(item) {
    const fresh = item.kind === "snapshot" && !this.mirror.hasSnapshot;
    const changed = this.mirror.apply(item);
    if (fresh && this.mirror.hasSnapshot) {
      const was = this.downSince;
      this.downSince = null;
      this.lastError = null;
      this.backoff = BACKOFF[0];
      for (const id of this.details.keys()) if (!this.mirror.threads.has(id)) this.details.delete(id);
      log(`${this.label}: snapshot seq ${this.mirror.sequence}, ${this.mirror.threads.size} threads` +
        (this.connected ? `, back after ${Math.round((Date.now() - was) / 1000)} s` : ""));
      this.connected = true;
    }
    if (!changed) return;
    for (const id of changed) this.consider(id);
    this.schedulePush();
  }

  consider(id) {
    const thread = this.mirror.threads.get(id);
    if (thread && wantsRead(thread, this.details.get(id), Date.now()) && !this.reading.has(id) && !this.queue.includes(id)) {
      this.queue.push(id);
      this.pump();
    }
  }

  pump() {
    while (this.reading.size < READS && this.queue.length) {
      const id = this.queue.shift();
      this.reading.add(id);
      this.read(id).finally(() => {
        this.reading.delete(id);
        this.consider(id);
        this.pump();
      });
    }
  }

  async read(id) {
    const thread = this.mirror.threads.get(id);
    if (!thread) return;
    try {
      const projection = await this.call("orchestration.getThreadProjection", { threadId: id });
      const details = detailsOf(projection, thread);
      const tries = this.retries.get(id) ?? 0;
      if (!details.settledReply && tries < REPLY_RETRIES) {
        // The run's reply isn't in yet: read again shortly, keeping what was read before.
        this.retries.set(id, tries + 1);
        setTimeout(() => this.consider(id), 3_000);
        if (this.details.has(id)) return;
        details.key = "";
      } else this.retries.delete(id);
      this.details.set(id, details);
      this.schedulePush();
    } catch (error) {
      log(`${this.label}: read ${id} failed: ${error.message}`);
    }
  }

  call(tag, payload) {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("socket not open"));
    const id = String(this.nextId++);
    return new Promise((resolve, reject) => {
      this.calls.set(id, { resolve, reject });
      ws.send(JSON.stringify({ _tag: "Request", id, tag, payload, headers: [] }));
      setTimeout(() => {
        if (this.calls.delete(id)) reject(new Error(`${tag} timed out`));
      }, 60_000);
    });
  }

  fail(generation, reason, wait) {
    if (generation !== this.generation) return;
    this.generation++; // ignore whatever the old socket says next
    const ws = this.ws;
    this.ws = null;
    try {
      ws?.close();
    } catch {}
    this.mirror.awaitSnapshot();
    for (const call of this.calls.values()) call.reject(new Error("socket dropped"));
    this.calls.clear();
    this.downSince ??= Date.now();
    this.lastError = reason;
    const delay = wait ?? this.backoff;
    this.backoff = Math.min(this.backoff * 2, BACKOFF[1]);
    log(`${this.label}: ${reason}; reconnecting in ${Math.round(delay / 1000)} s`);
    const next = this.generation;
    setTimeout(() => next === this.generation && this.connect(), delay);
    this.schedulePush();
  }

  /** A snooze that ran out sends no shell event: read what's due, and let the push see it. */
  recheck() {
    if (this.mirror.hasSnapshot) for (const id of readsDue(this.mirror, this.details, Date.now())) this.consider(id);
  }

  tick() {
    const ws = this.ws;
    if (!ws) return;
    // A socket that never opened, or stopped sending, is dead even if it never closed.
    if (Date.now() - this.lastFrameAt > SILENT) this.fail(this.generation, `no frame for ${SILENT / 1000} s`);
    else if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ _tag: "Ping" }));
  }

  schedulePush() {
    this.pushTimer ??= setTimeout(() => {
      this.pushTimer = null;
      this.push().catch((error) => log(`${this.label}: push failed: ${error.message}`));
    }, PUSH_AFTER);
  }

  get live() {
    return this.ws?.readyState === WebSocket.OPEN && this.mirror.hasSnapshot && this.downSince === null;
  }

  async push() {
    if (this.pushing) return this.schedulePush();
    if (!this.env) return;
    const now = Date.now();
    const live = this.live;
    // A short drop keeps the last push: its rows stay fresh in the app for 15 minutes.
    if (!live && this.refusedAt === null && now - (this.downSince ?? now) < DOWN_AFTER) return;
    this.pushing = true;
    try {
      const threads = live
        ? [...this.mirror.threads.values()].filter(listed).map((thread) => feedThread(this.env, thread, this.details.get(thread.id), now))
        : [];
      const out = JSON.parse(await run("python3", [INBOX, "live"], JSON.stringify({ env: this.env, threads })));
      this.name = out.machine;
      const health = healthNeeds(
        { machine: out.machine, downSince: this.downSince, lastError: this.lastError, expiresAt: this.expiresAt, refusedAt: this.refusedAt, link: README },
        now,
      );
      const body = { machine: out.machine, live, needs: [...health, ...out.needs] };
      const signature = JSON.stringify(body);
      if (signature === this.lastPushed && now - this.lastPushAt < HEARTBEAT) return;
      const input = JSON.stringify({ ...body, readAt: iso(now) });
      if (DRY) log(`${this.label}: would push ${input}`);
      else await run(CHIEF_BIN, ["record_live", "-"], input);
      const changed = signature !== this.lastPushed;
      this.lastPushed = signature;
      this.lastPushAt = now;
      if (changed)
        log(`${this.label}: pushed ${out.machine} ${live ? "live" : "down"}, ${out.needs.length} calls, ${health.length} health` +
          (out.needs.length ? `: ${out.needs.map((need) => need.title).join(" · ").slice(0, 200)}` : ""));
    } finally {
      this.pushing = false;
    }
  }
}

const sessions = (process.env.CHIEF_FEEDER_SESSIONS ?? "~/.config/chief/devbox-session.json,~/.config/chief/mac-session.json")
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean)
  .map((entry) => {
    const [file, origin] = entry.split("=");
    return new Machine(home(file), origin);
  });

for (const machine of sessions) machine.connect();
setInterval(() => {
  for (const machine of sessions) machine.tick();
}, PING);
setInterval(() => {
  for (const machine of sessions) machine.recheck();
  for (const machine of sessions) machine.push().catch((error) => log(`${machine.label}: push failed: ${error.message}`));
}, TICK);
for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => process.exit(0));
log(`chief feeder: ${sessions.map((machine) => machine.label).join(", ")}${DRY ? " (dry run)" : ""}`);


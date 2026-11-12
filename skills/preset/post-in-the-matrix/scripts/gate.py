#!/usr/bin/env python3
"""Wakes a scheduled channel check only when there's something new for it to act on.

A scheduled agent that reads #plug-into-the-matrix every few minutes wakes a model on
every tick, though almost every tick finds nothing. This gate runs on a timer instead
(references/gate.md): it reads the channel and the PRs it names without a model, and
POSTs to the check's T3 webhook only when one of these appeared since its last wake:

- a message or thread reply from someone other than your human, posted in the last
  `ask_hours` (a new request, a re-review ask, or anything the check must judge);
- a PR named in the channel turning merged or closed;
- your human's latest review on such a PR changing (an approval, a dismissal), or, while
  it stays dismissed, a new head commit.

The woken check still decides everything; the gate only decides whether it runs. So a
signal here is a superset of what the check acts on, and a run that finds nothing to do
is the gate's only false positive. A wake also goes out when `quiet_hours` pass with
none, which retries whatever a failed run left undone, and on every run once the gate
itself has failed for `fail_open_minutes`, so a broken gate falls back to the old
cadence and the check's own read reports what broke.

  gate.py --config FILE             check once, and wake the check if anything is new
  gate.py --config FILE --dry-run   print what it would send, and change nothing

The config is JSON; references/gate.md lists its keys. The Executor key and the
webhook URL stay in files the config names, and nothing here prints either. State (the
signals seen at the last wake, and a cache of thread replies) lives in `state_file`.
Exits 1 when a read or the wake fails; the next run tries again."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

USER_AGENT = "post-in-the-matrix-gate/1"
DEFAULTS = {"ask_hours": 72, "lookback_days": 30, "quiet_hours": 2, "fail_open_minutes": 60}


@dataclass(frozen=True)
class Message:
    ts: str
    user: str
    text: str
    replies: int = 0
    latest: str = ""  # the channel listing's "latest:" stamp for a parent's replies


# ---- Parsing what the Slack MCP returns -------------------------------------------------

CHANNEL_HEAD = re.compile(r"^=== Message from (?:.*?\(([UW][A-Z0-9]+)\))?.*?===\s*$", re.M)
REPLY_HEAD = re.compile(r"^(?:--- Reply \d+ of \d+ ---|=== THREAD PARENT MESSAGE ===)\s*$", re.M)
TS_LINE = re.compile(r"^Message TS: (\d+\.\d+)\s*$", re.M)
FROM_LINE = re.compile(r"^From: (?:.*?\(([UW][A-Z0-9]+)\))?.*$", re.M)
THREAD_LINE = re.compile(r"^Thread: (\d+) repl(?:y|ies)(?: \(latest: ([^)]*)\))?\s*$", re.M)
CURSOR = re.compile(r"cursor: `([^`]+)`")


def parse_channel(text: str) -> list[Message]:
    """The messages in one slack_read_channel page, in the order listed."""
    heads = list(CHANNEL_HEAD.finditer(text))
    out = []
    for head, nxt in zip(heads, heads[1:] + [None]):
        block = text[head.end():nxt.start() if nxt else len(text)]
        ts = TS_LINE.search(block)
        if not ts:
            continue
        thread = THREAD_LINE.search(block)
        out.append(Message(ts.group(1), head.group(1) or "", block,
                           int(thread.group(1)) if thread else 0,
                           (thread.group(2) or "") if thread else ""))
    return out


def parse_thread(text: str) -> list[Message]:
    """The replies in one slack_read_thread result, without the parent."""
    replies_at = text.find("=== THREAD REPLIES")
    if replies_at < 0:
        return []
    body = text[replies_at:]
    heads = list(REPLY_HEAD.finditer(body))
    out = []
    for head, nxt in zip(heads, heads[1:] + [None]):
        block = body[head.end():nxt.start() if nxt else len(body)]
        ts, who = TS_LINE.search(block), FROM_LINE.search(block)
        if ts:
            out.append(Message(ts.group(1), (who.group(1) or "") if who else "", block))
    return out


def next_cursor(pagination_info: str) -> str | None:
    match = CURSOR.search(pagination_info or "")
    return match.group(1) if match else None


# ---- What a message names ---------------------------------------------------------------

def pr_numbers(text: str, repo: str) -> set[int]:
    """PRs in repo that text names: GitHub and Graphite links, and a bare #<n>."""
    owner, name = (re.escape(part) for part in repo.split("/"))
    found = re.findall(rf"github\.com/{owner}/{name}/pull/(\d+)", text)
    found += re.findall(rf"app\.graphite\.(?:com|dev)/github/pr/{owner}/{name}/(\d+)", text)
    found += re.findall(r"(?<![\w/&#])#(\d{2,6})\b", text)
    return {int(n) for n in found}


LINEAR = re.compile(r"<?https://linear\.app/[\w-]+/review/([\w-]+)[^|>\s]*(?:\|([^>]*)>)?")


def linear_keys(text: str) -> set[str]:
    """What to search PR titles for, per Linear review link: its issue id (DEV-123) when
    the slug or title holds one, else the link's title."""
    keys = set()
    for slug, title in LINEAR.findall(text):
        title = html.unescape(title or "").strip()
        issue = re.search(r"\b([a-z]+-\d+)\b", slug, re.I) or re.search(r"\b([A-Z]+-\d+)\b", title)
        if issue:
            keys.add(issue.group(1).upper())
        elif title and not re.fullmatch(r"#\d+", title):  # a bare #<n> title is pr_numbers'
            keys.add(title)
    return keys


# ---- The decision ---------------------------------------------------------------------

VOLATILE = re.compile(r"^(?:Thread|Reactions): .*$", re.M)


def body_hash(text: str) -> str:
    """A message's text without its reply count and reactions, hashed, so an edit (say,
    an FYI that gains a mention) is news while a new reaction or reply count isn't."""
    return hashlib.sha256(VOLATILE.sub("", text).strip().encode()).hexdigest()[:10]


def signals(messages: list[Message], prs: dict[int, dict], *, me: str, now: float,
            ask_hours: float) -> set[str]:
    """Everything the check could act on now, one string per fact. A string the last wake
    didn't see is news. prs maps a number to {state, headRefOid, reviews}, where reviews
    are your human's, oldest first, each {state, commit, at}. Only an approval or its
    dismissal counts: a comment or a change request leaves the check nothing to do. An
    approval is known by when it was sent, so approving the same head again is news."""
    out = {f"msg:{m.ts}:{body_hash(m.text)}" for m in messages
           if m.user != me and float(m.ts) >= now - ask_hours * 3600}
    for number, pr in prs.items():
        if pr["state"] in ("MERGED", "CLOSED"):
            out.add(f"pr:{number}:{pr['state']}")
        decisive = [r for r in pr["reviews"] if r["state"] in ("APPROVED", "DISMISSED")]
        if decisive:
            review = decisive[-1]
            if review["state"] == "APPROVED":
                out.add(f"pr:{number}:approved:{review['commit'][:9]}:{review['at']}")
            else:
                out.add(f"pr:{number}:dismissed:{review['commit'][:9]}:head:{pr['headRefOid'][:9]}")
    return out


def decide(current: set[str], state: dict, *, now: float, quiet_hours: float) -> list[str]:
    """Why to wake the check now, or [] to let it sleep."""
    new = sorted(current - set(state.get("seen", [])))
    if new:
        return new
    if now - state.get("last_wake", 0) >= quiet_hours * 3600:
        return ["quiet: no wake for %g hours" % quiet_hours]
    return []


def fail_open(state: dict, *, now: float, minutes: float) -> bool:
    """Whether a failing gate should wake the check anyway: it has failed for `minutes`."""
    return now - state.get("last_ok", now) >= minutes * 60


# ---- Reading Slack through Executor ---------------------------------------------------

class Executor:
    """A minimal MCP client for Executor's `call` tool, over streamable HTTP."""

    def __init__(self, url: str, key: str):
        self.url, self.key, self.session, self.ids = url, key, None, 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": USER_AGENT, "version": "1"}})
        self._rpc("notifications/initialized", {}, notify=True)

    def _rpc(self, method: str, params: dict, notify: bool = False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            self.ids += 1
            body["id"] = self.ids
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "User-Agent": USER_AGENT}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.url, json.dumps(body).encode(), headers, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            self.session = response.headers.get("Mcp-Session-Id") or self.session
            kind, raw = response.headers.get("Content-Type", ""), response.read().decode()
        if notify:
            return None
        frames = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")] \
            if "event-stream" in kind else [raw]
        replies = [json.loads(frame) for frame in frames if frame.strip()]
        reply = next((r for r in replies if r.get("id") == body["id"]), None)
        if reply is None or "error" in reply:
            raise RuntimeError(f"Executor {method}: {reply and reply.get('error')}")
        return reply["result"]

    def call(self, path: str, tool_input: dict) -> dict:
        result = self._rpc("tools/call", {"name": "call", "arguments": {"calls": {"path": path, "input": tool_input}}})
        outer = json.loads(result["content"][0]["text"])
        execution = outer.get("execution") or {}
        inner = execution.get("value") or {}
        if outer.get("status") != "completed" or not execution.get("ok") or not inner.get("ok"):
            raise RuntimeError(f"Executor call {path} did not complete: {str(outer)[:300]}")
        value = inner["value"]
        if value.get("isError"):
            raise RuntimeError(f"{path} failed: {str(value)[:300]}")
        return json.loads(value["content"][0]["text"])


def read_channel(slack, config: dict, state: dict, now: float) -> list[Message]:
    """Every message and reply in the lookback. A thread is read again when its latest
    reply moved since the last run, or while it holds a reply young enough to be an ask,
    since an edit moves neither. slack(name, input) calls one Slack MCP tool."""
    channel = config["channel"]
    oldest = str(int(now - config["lookback_days"] * 86400))
    parents, cursor = [], None
    while True:
        page = slack("slack_read_channel", {"channel_id": channel, "oldest": oldest, "limit": 100,
                                            **({"cursor": cursor} if cursor else {})})
        parents += parse_channel(page["messages"])  # a reply without it is a failed read
        cursor = next_cursor(page.get("pagination_info", ""))
        if not cursor:
            break
    cache, threads = state.get("threads", {}), {}
    for parent in parents:
        if not parent.replies:
            continue
        cached = cache.get(parent.ts)
        young = cached and any(float(r["ts"]) >= now - config["ask_hours"] * 3600 for r in cached["replies"])
        if cached and not young and cached["latest"] == parent.latest and cached["count"] == parent.replies:
            threads[parent.ts] = cached
            continue
        read = slack("slack_read_thread", {"channel_id": channel, "message_ts": parent.ts})
        threads[parent.ts] = {"latest": parent.latest, "count": parent.replies,
                              "replies": [asdict(r) for r in parse_thread(read.get("messages", ""))]}
    state["threads"] = threads
    return parents + [Message(**r) for t in threads.values() for r in t["replies"]]


# ---- Reading GitHub through gh ----------------------------------------------------------

def gh(*args: str) -> str:
    run = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if run.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {run.stderr.strip()[:300]}")
    return run.stdout


def resolve_linear(keys: set[str], config: dict, state: dict, now: float) -> set[int]:
    """PR numbers for Linear review links, by a PR title search per key, searched again
    hourly: an issue can gain PRs, and GitHub's search index lags a new one. Every hit is
    kept while its link stays in the lookback, since a PR's title can change after."""
    cache = {k: v for k, v in state.get("linear", {}).items() if k in keys}
    found = set()
    for key in sorted(keys):
        entry = cache.get(key)
        if entry is None or now - entry["at"] >= 3600:
            query = f"{key} in:title" if re.fullmatch(r"[A-Z]+-\d+", key) else f'"{key}" in:title'
            hits = json.loads(gh("pr", "list", "--repo", config["repo"], "--state", "all",
                                 "--search", query, "--json", "number", "--limit", "20"))
            known = entry["prs"] if entry else []
            entry = cache[key] = {"prs": sorted({*known, *(hit["number"] for hit in hits)}), "at": now}
        found.update(entry["prs"])
    state["linear"] = cache
    return found


def pr_states(numbers: set[int], config: dict) -> dict[int, dict]:
    """State, head, and your human's reviews for each number that is a PR, 50 a query."""
    owner, name = config["repo"].split("/")
    out = {}
    ordered = sorted(numbers)
    for start in range(0, len(ordered), 50):
        fields = " ".join(
            f'p{n}: pullRequest(number: {n}) {{ number state headRefOid '
            f'reviews(last: 20, author: "{config["github_login"]}") {{ nodes {{ state submittedAt commit {{ oid }} }} }} }}'
            for n in ordered[start:start + 50])
        query = f'query {{ repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'
        run = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                             capture_output=True, text=True, timeout=120)
        try:
            reply = json.loads(run.stdout)
            repo = reply["data"]["repository"]
        except (ValueError, KeyError, TypeError):
            raise RuntimeError(f"gh api graphql: {run.stderr.strip()[:300]}")
        # NOT_FOUND is a number that isn't a PR, such as an issue; any other error leaves
        # a null that would read as one, so the read failed.
        failed = [e for e in reply.get("errors") or [] if e.get("type") != "NOT_FOUND"]
        if failed:
            raise RuntimeError(f"gh api graphql: {failed[0].get('message', failed[0])}"[:300])
        for pr in repo.values():
            if pr:
                out[pr["number"]] = {"state": pr["state"], "headRefOid": pr["headRefOid"],
                                     "reviews": [{"state": r["state"], "commit": (r.get("commit") or {}).get("oid", ""),
                                                  "at": r.get("submittedAt") or ""}
                                                 for r in pr["reviews"]["nodes"]]}
    return out


def track(named: set[int], state: dict, lookup) -> dict[int, dict]:
    """The PRs to watch: those named now, and every watched PR still open at the last run,
    so a review thread's PR stays watched after its link leaves the lookback. One the
    lookup didn't return stays watched, since only a closed PR leaves.
    lookup(numbers) returns pr_states' shape."""
    was_open = set(state.get("open", []))
    prs = lookup(named | was_open)
    state["open"] = sorted({n for n, pr in prs.items() if pr["state"] == "OPEN"} | (was_open - prs.keys()))
    return prs


# ---- One run --------------------------------------------------------------------------

def load_config(path: str) -> dict:
    config = {**DEFAULTS, **json.loads(Path(path).expanduser().read_text())}
    missing = [k for k in ("channel", "slack_account", "slack_user", "github_login", "repo",
                           "executor_url", "executor_key_file", "webhook_url_file", "state_file")
               if k not in config]
    if missing:
        raise SystemExit(f"gate.py: the config lacks {', '.join(missing)}")
    return config


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as file:
        json.dump(state, file)
    os.replace(file.name, path)


def wake(config: dict, reasons: list[str], last_wake: float) -> None:
    """POST to the check's webhook. wakeId hashes the reasons with the last delivered
    wake, so a retried POST repeats its id and runs the check once when the schedule
    dedupes on {{body.wakeId}}, while a later wake for the same reasons (the next quiet
    or fail-open wake) gets a new one. T3 keeps a replay key for days."""
    url = Path(config["webhook_url_file"]).expanduser().read_text().strip()
    seed = "\n".join([repr(last_wake), *reasons])
    body = {"wakeId": hashlib.sha256(seed.encode()).hexdigest()[:24], "reasons": reasons[:50]}
    request = urllib.request.Request(url, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status >= 300:
            raise RuntimeError(f"webhook answered {response.status}")


def gather(config: dict, state: dict, now: float) -> set[str]:
    key = Path(config["executor_key_file"]).expanduser().read_text().strip()
    executor = Executor(config["executor_url"], key)

    def slack(name: str, tool_input: dict) -> dict:
        return executor.call(f'tools["slack-mcp"].{name}', {"accountId": config["slack_account"], "input": tool_input})

    messages = read_channel(slack, config, state, now)
    # Only teammates' messages name PRs the check acts on; your human's own posts ask others.
    theirs = [m for m in messages if m.user != config["slack_user"]]
    named = set().union(*(pr_numbers(m.text, config["repo"]) for m in theirs))
    named |= resolve_linear({k for m in theirs for k in linear_keys(m.text)}, config, state, now)
    prs = track(named, state, lambda numbers: pr_states(numbers, config))
    return signals(messages, prs, me=config["slack_user"], now=now, ask_hours=config["ask_hours"])


def run(config: dict, dry_run: bool, now: float | None = None) -> int:
    now = time.time() if now is None else now
    state_path = Path(config["state_file"]).expanduser()
    state = load_state(state_path)
    try:
        current = gather(config, state, now)
    except Exception as error:  # whatever broke the read, failing open must still run
        print(f"gate: read failed: {type(error).__name__}: {error}", file=sys.stderr)
        if dry_run:
            return 1
        # A gate that never succeeded counts its failures from the first one.
        state.setdefault("last_ok", now)
        if fail_open(state, now=now, minutes=config["fail_open_minutes"]):
            try:
                wake(config, ["gate failing since " + time.strftime("%H:%M", time.localtime(state["last_ok"]))],
                     state.get("last_wake", 0))
                state["last_wake"] = now
            except Exception as wake_error:
                print(f"gate: wake failed too: {wake_error}", file=sys.stderr)
        save_state(state_path, state)
        return 1
    reasons = decide(current, state, now=now, quiet_hours=config["quiet_hours"])
    if dry_run:
        print(json.dumps({"wake": bool(reasons), "reasons": reasons, "signals": len(current)}))
        return 0
    if reasons:
        try:
            wake(config, reasons, state.get("last_wake", 0))
        except Exception as error:
            print(f"gate: wake failed, next run retries: {error}", file=sys.stderr)
            return 1
        state["last_wake"] = now
        print(f"gate: woke the check: {', '.join(reasons[:10])}")
    state["seen"], state["last_ok"] = sorted(current), now
    save_state(state_path, state)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(load_config(args.config), args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

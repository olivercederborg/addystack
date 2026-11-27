"""Collects what replay.py needs from coordinator transcripts.

usage: collect.py OUT HOST=ROOT [HOST=ROOT ...]
Each ROOT is a Claude Code projects folder (~/.claude/projects, or a copy of another
machine's). A coordinator transcript is a top-level session file with a `Coordinator
heartbeat` prompt. Writes to OUT: turns.json (every turn of those sessions, deduplicated
across forked files), refs_<HOST>.json (thread ids each session names, for dbdump.py),
starts.json (runs each coordinator started: send, launch, delegate, or an answered
question), and pr_mentions.json (PRs each names, with times)."""
import collections, json, re, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

SINCE = "2026-10-29"
SCHED = re.compile(r"(Coordinator (heartbeat|startup check)|Daily develop sync|Hourly owner check)")
THREAD = re.compile(r"(mcp:launch:[0-9a-f]{64}|thread:delegated-task:command%3A[^\s\"'>)\]\\<]+|mcp:[0-9a-f]{8}-[0-9a-f-]{27})")
PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
START = {"mcp__t3-code__t3_thread_send", "mcp__t3-code__t3_thread_launch", "mcp__t3-code__delegate_task",
         "mcp__t3-code__t3_pending_request"}


def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def text_of(c):
    if isinstance(c, str):
        return c
    out = []
    for x in c or []:
        if isinstance(x, dict) and x.get("type") == "text":
            out.append(x.get("text", ""))
        elif isinstance(x, dict) and x.get("type") == "tool_result":
            cc = x.get("content"); out.append(cc if isinstance(cc, str) else text_of(cc))
    return "\n".join(out)


def is_tool_result(d):
    c = (d.get("message") or {}).get("content")
    return isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c)


def records(path):
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if (d.get("timestamp") or "") >= SINCE:
            yield d, line


def coordinators(root):
    for path in Path(root).expanduser().glob("*/*.jsonl"):
        if any(d.get("type") == "user" and not is_tool_result(d) and SCHED.match(text_of((d.get("message") or {}).get("content")).lstrip())
               for d, _ in records(path)):
            yield path


def turns(path, host):
    out, cur, seen = [], None, set()
    for d, _ in records(path):
        t, m = ts(d["timestamp"]), d.get("message") or {}
        if d.get("type") == "user" and not is_tool_result(d) and not d.get("isMeta"):
            text = text_of(m.get("content")).lstrip()
            cur = {"host": host, "file": str(path), "t": t, "prompt": text[:400], "sched": bool(SCHED.match(text)),
                   "tools": [], "ctx": 0, "out": 0, "act_s": 0, "reply": "", "last": t}
            out.append(cur)
            continue
        if not cur or d.get("type") not in ("assistant", "user"):
            continue
        if 0 <= t - cur["last"] < 3600:
            cur["act_s"] += t - cur["last"]
        cur["last"] = t
        if d.get("type") == "assistant":
            if m.get("id") not in seen:
                seen.add(m.get("id")); u = m.get("usage") or {}
                cur["out"] += u.get("output_tokens") or 0
                cur["ctx"] += sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    cur["reply"] = c["text"][:600]
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    i = c.get("input") or {}
                    arg = i.get("command") or i.get("skill") or i.get("file_path") or i.get("threadId") or i.get("title") or json.dumps(i)[:120]
                    cur["tools"].append(f"{c['name']}:{str(arg)[:200]}")
    return out


def starts(path):
    """(time, thread id, tool) for each run the coordinator started in a worker."""
    out, pending = [], {}
    for d, _ in records(path):
        for c in (d.get("message") or {}).get("content") or [] if isinstance((d.get("message") or {}).get("content"), list) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c["name"] in START:
                i = c.get("input") or {}
                if c["name"].endswith("pending_request") and i.get("action") != "respond":
                    continue
                if i.get("threadId"):
                    out.append((ts(d["timestamp"]), i["threadId"], c["name"]))
                else:
                    pending[c["id"]] = (ts(d["timestamp"]), c["name"])
            if c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                t0, name = pending.pop(c["tool_use_id"])
                out += [(t0, i.rstrip(".,;"), name) for i in set(THREAD.findall(json.dumps(c.get("content")))[:2])]
    return out


def mentions(path):
    """{(repo, n): [times]} for each PR the transcript names, as a URL or, in a Franklin
    project, as a bare #5NNN."""
    found = collections.defaultdict(list)
    franklin = "franklin" in str(path)
    for d, line in records(path):
        t = ts(d["timestamp"])
        for repo, n in set(PR_URL.findall(line)):
            if not repo.startswith(("acme/", "Effect-TS/", "apify/", "o/r")):
                found[(repo, int(n))].append(t)
        if franklin:
            for n in set(re.findall(r"(?<![\w/])#(5\d{3})\b", line)):
                found[("hifranklin-tech/franklin-next", int(n))].append(t)
    return found


def main(out, roots):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    all_turns, refs, start, ment = [], collections.defaultdict(dict), {}, []
    for spec in roots:
        host, root = spec.split("=", 1)
        for path in coordinators(root):
            sess = path.stem
            all_turns += turns(path, host)
            start[sess] = starts(path)
            refs[host][sess] = sorted({i.rstrip(".,;") for i in THREAD.findall(path.read_text(errors="replace"))}
                                      | {i for _, i, _ in start[sess]})
            ment += [[sess, r, n, sorted(v)] for (r, n), v in mentions(path).items()]
    seen, kept = set(), []
    for x in sorted(all_turns, key=lambda x: (x["t"], len(x["tools"]))):
        key = (round(x["t"]), x["prompt"][:80])
        if key not in seen:
            seen.add(key); kept.append(x)
    json.dump(kept, open(out / "turns.json", "w"))
    json.dump(start, open(out / "starts.json", "w"))
    json.dump(ment, open(out / "pr_mentions.json", "w"))
    for host, sessions in refs.items():
        json.dump(sessions, open(out / f"refs_{host}.json", "w"))
    print(f"{len(kept)} turns, {sum(x['sched'] for x in kept)} scheduled, {len(start)} coordinator sessions")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

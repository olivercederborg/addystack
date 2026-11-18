#!/usr/bin/env python3
"""The reply log: the reply-shape rules the Stop hooks count instead of sending a reply back.

A Stop hook judges a reply after T3 has posted it, so each send-back posts a second copy of
the card. In the 7 days to Nov 18, 2026, 457 Stop send-backs reached Claude Code sessions
on two machines, and 239 of them carried a format check: the glance's word count, the
fact table's limits, or a scope-grill round's word count (suite-audit R148 F4, R153). The
user's call on Nov 18, 2026: count the format rules weekly instead, and keep sending back
the turn block and merge options, which routine_stop.py and merge-gate.py read. So reply_budget.py
and routine_stop.py append a row here for each format rule a reply breaks, and
`addystack replies-report` sums them for a date range.

One JSON object per line in reply-log.jsonl in the state folder (ADDYSTACK_REPLY_LOG
overrides the file): `time` (UTC, ISO 8601), `hook`, `rule`, `session`, `turn` (Codex's
turn_id, else the transcript's prompt count), `cwd`, `detail` (what broke, such as "107
words, over 100"), and `headline` (the reply's first line, cut to 100 characters). The
file is the user's alone (0600), and a write that fails is skipped, so the log never
blocks a stop."""
from __future__ import annotations

import json, os, sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolved, transcripts  # noqa: E402

HEADLINE = 100  # characters of the reply's first line a row keeps


def path() -> Path:
    override = os.environ.get("ADDYSTACK_REPLY_LOG")
    return Path(override).expanduser() if override else resolved.STATE.expanduser().parent / "reply-log.jsonl"


def headline(reply: str) -> str:
    first = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    return first[:HEADLINE]


def record(event: dict, hook: str, broken: Iterable[Tuple[str, str]]) -> None:
    """Appends a row for each (rule, detail) the reply in event breaks."""
    broken = list(broken)
    if not broken:
        return
    turn = event.get("turn_id")
    if turn is None and event.get("transcript_path"):
        turn = len(transcripts.exchanges(event["transcript_path"]))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    common = {"time": now, "hook": hook, "session": event.get("session_id"), "turn": turn,
              "cwd": event.get("cwd"), "headline": headline(event.get("last_assistant_message") or "")}
    rows = "".join(json.dumps({**common, "rule": rule, "detail": detail}, ensure_ascii=False) + "\n"
                   for rule, detail in broken)
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Only the user reads it: a row holds a reply's headline, and the state folder is world-readable.
        with open(os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", encoding="utf-8") as log:
            log.write(rows)
    except OSError:
        pass


def rows(since: date, until: date) -> List[dict]:
    """The log's rows from since up to, not including, until (UTC days). Lines that don't
    parse are skipped."""
    found = []
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        try:
            row = json.loads(line)
            day = datetime.fromisoformat(row["time"]).astimezone(timezone.utc).date()
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if since <= day < until:
            found.append(row)
    return found


def summary(found: List[dict], top: int = 3) -> dict:
    """Per rule: its violations, the sessions they came from, and the top sessions, each
    with its count and its latest row."""
    by_rule = defaultdict(list)
    for row in found:
        by_rule[(row.get("hook"), row.get("rule"))].append(row)
    out = []
    for (hook, rule), group in sorted(by_rule.items(), key=lambda item: -len(item[1])):
        sessions = Counter(row.get("session") for row in group)
        latest = {row.get("session"): row for row in sorted(group, key=lambda row: row["time"])}
        out.append({"hook": hook, "rule": rule, "violations": len(group), "sessions": len(sessions),
                    "top": [{"session": session, "violations": count, "time": latest[session]["time"],
                             "detail": latest[session].get("detail"), "headline": latest[session].get("headline")}
                            for session, count in sessions.most_common(top)]})
    return {"violations": len(found), "rules": out}


def markdown(report: dict, since: date, until: date) -> str:
    last = until - timedelta(days=1)
    lines = [f"Reply log, {since} to {last}: {report['violations']} violations ({path()})", ""]
    if not report["rules"]:
        return "\n".join(lines + ["None logged."])
    lines += ["| Hook | Rule | Violations | Sessions |", "|---|---|---|---|"]
    lines += [f"| {item['hook']} | {item['rule']} | {item['violations']} | {item['sessions']} |"
              for item in report["rules"]]
    for item in report["rules"]:
        lines += ["", f"**{item['rule']}**, top sessions:"]
        lines += [f"- `{str(top['session'])[:8]}` × {top['violations']}, latest {top['time'][:16]}: "
                  f"{top['detail']} · \"{top['headline']}\"" for top in item["top"]]
    return "\n".join(lines)

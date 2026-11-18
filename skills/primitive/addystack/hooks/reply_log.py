#!/usr/bin/env python3
"""The reply log: the reply-shape rules the Stop hooks count instead of sending a reply back.

A Stop hook judges a reply after T3 has posted it, so each send-back posts a second copy of
the card. In the 7 days to Nov 18, 2026, 457 Stop send-backs reached Claude Code sessions
on two machines, and 239 of them carried a format check: the glance's word count, the
fact table's limits, or a scope-grill round's word count (suite-audit R148 F4, R153). The
user's call on Nov 18, 2026: count the format rules weekly instead, and keep sending back
the turn block and merge options, which routine_stop.py and merge-gate.py read. So reply_budget.py
appends a row here for each format rule a reply breaks.

One JSON object per line in reply-log.jsonl in the state folder (ADDYSTACK_REPLY_LOG
overrides the file): `time` (UTC, ISO 8601), `hook`, `rule`, `session`, `turn` (Codex's
turn_id, else the transcript's prompt count), `cwd`, `detail` (what broke, such as "107
words, over 100"), and `headline` (the reply's first line, cut to 100 characters). A
write that fails is skipped, so the log never blocks a stop."""
from __future__ import annotations

import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Tuple

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
        with open(target, "a", encoding="utf-8") as log:
            log.write(rows)
    except OSError:
        pass

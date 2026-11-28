#!/usr/bin/env python3
"""Measures what one eval player run cost: wall time, tokens by kind, and USD at list
rates, summed over the player and every child it started, recursively.

evals.py calls measure() when it saves a run's replies, and writes the result as the
run's cost.json."""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
from collections import Counter
from typing import Iterable, Literal, TypedDict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kit_path  # noqa: E402
sys.path.insert(0, str(kit_path.tool() / "hooks"))
import t3_child  # noqa: E402  owns the T3 state-DB schema.
import transcript as jsonl  # noqa: E402  the JSONL reader; measure's argument takes the name.

PROJECTS = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude")) / "projects"
CODEX_SESSIONS = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")) / "sessions"
RATES = pathlib.Path.home() / ".t3" / "userdata" / "usage-model-rates.json"
# Each kind of token counted, and the key of its per-token rate in T3's rates file.
# Claude Code writes its prompt cache for 1 hour, which costs more than a 5-minute write.
RATE_KEYS = {
    "input": "input_cost_per_token",
    "cache_write_5m": "cache_creation_input_token_cost",
    "cache_write_1h": "cache_creation_input_token_cost_above_1hr",
    "cache_read": "cache_read_input_token_cost",
    "output": "output_cost_per_token",
}
# Claude Code's own placeholder lines, such as an API error, carry no billed usage.
SYNTHETIC = "<synthetic>"


class Tokens(TypedDict):
    input: int  # fresh input only; Codex counts its cached input inside input_tokens
    cache_write: int  # Claude 5-minute and 1-hour writes together
    cache_read: int
    output: int  # Codex counts reasoning inside output_tokens


class Session(TypedDict):
    path: str
    driver: Literal["claudeAgent", "codex"]
    models: dict[str, Tokens]
    usd: float | None  # None when one of its models has no rate


class Cost(TypedDict):
    wall_s: float  # the player's transcript, first timestamp to last
    tokens: Tokens
    usd: float | None  # None when any session's is
    sessions: list[Session]  # the player, its native subagents, and T3 children, recursively
    rates: dict[str, dict[str, float]]  # the per-token rates applied, by model
    missing: list[str]  # sessions T3 knows of whose transcript isn't on this machine
    unpriced: list[str]  # model ids the rates file doesn't list


def measure(transcript: pathlib.Path) -> Cost:
    transcript = pathlib.Path(transcript)
    # A Claude transcript is named <session id>.jsonl; a Codex rollout records its id inside.
    root = jsonl.codex_session_id(transcript) if jsonl.is_codex(transcript) else transcript.stem
    rates, applied, missing, unpriced, sessions = _rates(), {}, [], [], []
    seen = set()
    for driver, native_id in t3_child.session_tree(root):
        paths = _files(driver, native_id, transcript if native_id == root and driver != "codex" else None)
        if not paths:
            missing.append(f"{driver} {native_id}: no {'rollout' if driver == 'codex' else 'transcript'} file")
        for path in paths:
            usage = _codex_usage(path) if driver == "codex" else _claude_usage(path, seen)
            usd = 0.0
            for model, counts in usage.items():
                price = _price(model, counts, rates)
                if price is None:
                    usd = None
                    if model not in unpriced:
                        unpriced.append(model)
                else:
                    applied[model] = {kind: rates[model][key] for kind, key in RATE_KEYS.items() if key in rates[model]}
                    usd = None if usd is None else usd + price
            sessions.append({"path": str(path), "driver": driver, "usd": usd,
                             "models": {model: _tokens(counts) for model, counts in usage.items()}})
    return {
        "wall_s": _wall_s(transcript),
        "tokens": _sum(tokens for s in sessions for tokens in s["models"].values()),
        "usd": _total(s["usd"] for s in sessions),
        "sessions": sessions,
        "rates": applied,
        "missing": missing,
        "unpriced": unpriced,
    }


def add(costs: Iterable[Cost]) -> Cost:
    """Sums one trial's scenarios into one cost."""
    costs = list(costs)
    return {
        "wall_s": sum(c["wall_s"] for c in costs),
        "tokens": _sum(c["tokens"] for c in costs),
        "usd": _total(c["usd"] for c in costs),
        "sessions": [s for c in costs for s in c["sessions"]],
        "rates": {model: rate for c in costs for model, rate in c["rates"].items()},
        "missing": [m for c in costs for m in c["missing"]],
        "unpriced": sorted({m for c in costs for m in c["unpriced"]}),
    }


def _files(driver, native_id, root=None):
    """The files that hold one session's usage. A Claude session's native subagents write
    their own files under <id>/subagents/; T3 records none of them. A Codex session can
    span several rollout files, and every one is billed, abandoned branches included."""
    if driver == "codex":
        return sorted(CODEX_SESSIONS.glob(f"*/*/*/rollout-*{native_id}*.jsonl"), key=lambda f: f.name)
    mains = [root] if root else sorted(PROJECTS.glob(f"*/{native_id}.jsonl"))
    return mains + [f for main in mains for f in sorted(main.with_suffix("").glob("subagents/**/*.jsonl"))]


def _claude_usage(path, seen):
    """Usage by model, counting each message.id once: Claude Code writes one line per
    content block of a reply, each with the reply's usage so far, so the last line wins.
    `seen` holds ids counted in earlier files, such as a resumed session's copied history."""
    last = {}
    for _, record in jsonl.records(path):
        message = record.get("message") if record.get("type") == "assistant" else None
        if isinstance(message, dict) and message.get("id") and message["id"] not in seen \
                and isinstance(message.get("usage"), dict) and message.get("model") != SYNTHETIC:
            last[message["id"]] = (message.get("model") or "unknown", message["usage"])
    seen.update(last)
    usage = {}
    for model, u in last.values():
        written = u.get("cache_creation_input_tokens") or 0
        split = u.get("cache_creation") or {}
        hour = split.get("ephemeral_1h_input_tokens") or 0
        usage.setdefault(model, Counter()).update({
            "input": u.get("input_tokens") or 0,
            "cache_write_5m": written - hour,
            "cache_write_1h": hour,
            "cache_read": u.get("cache_read_input_tokens") or 0,
            "output": u.get("output_tokens") or 0,
        })
    return usage


def _codex_usage(path):
    """The file's last cumulative token_count, under the model of its last turn_context.
    Codex counts cached input inside input_tokens, and reasoning inside output_tokens."""
    total, model = None, "unknown"
    for _, record in jsonl.records(path):
        payload = record.get("payload") or {}
        if record.get("type") == "turn_context" and payload.get("model"):
            model = payload["model"]
        elif payload.get("type") == "token_count" and (payload.get("info") or {}).get("total_token_usage"):
            total = payload["info"]["total_token_usage"]
    if total is None:
        return {}
    cached = total.get("cached_input_tokens") or 0
    return {model: Counter({
        "input": (total.get("input_tokens") or 0) - cached,
        "cache_write_5m": total.get("cache_write_input_tokens") or 0,
        "cache_read": cached,
        "output": total.get("output_tokens") or 0,
    })}


def _price(model, counts, rates):
    rate = rates.get(model)
    if rate is None:
        return None
    usd = 0.0
    for kind, count in counts.items():
        if count:
            if rate.get(RATE_KEYS[kind]) is None:
                return None
            usd += count * rate[RATE_KEYS[kind]]
    return usd


def _rates():
    return json.loads(RATES.read_text())["document"]


def _wall_s(path):
    stamps = [r["timestamp"] for _, r in jsonl.records(path) if isinstance(r.get("timestamp"), str)]
    if not stamps:
        return 0.0
    def parse(stamp):  # Before 3.11, fromisoformat rejects the trailing Z transcripts write.
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return (parse(stamps[-1]) - parse(stamps[0])).total_seconds()


def _tokens(counts):
    return {"input": counts["input"], "cache_write": counts["cache_write_5m"] + counts["cache_write_1h"],
            "cache_read": counts["cache_read"], "output": counts["output"]}


def _sum(tokens):
    total = Counter()
    for t in tokens:
        total.update(t)
    return {kind: total[kind] for kind in ("input", "cache_write", "cache_read", "output")}


def _total(values):
    values = list(values)
    return None if any(v is None for v in values) else sum(values)

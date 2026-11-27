#!/usr/bin/env python3
"""Runs the deterministic parts of a skill eval, so a change can show a pass table.

Scenarios load from every evals/*/evals.json. An agent starts the player and the
grader as T3 child tasks (see evals/README.md); this script writes their briefs,
saves the player's replies from its transcript, records the grades, and compares runs.

Usage:
  maintainer/evals.py list [skill]
  maintainer/evals.py start <skill> <id> OUT [--variant DIR]... [--rules DIR|none]
  maintainer/evals.py turns <skill> <id>
  maintainer/evals.py replies <skill> <id> OUT [--transcript FILE]
  maintainer/evals.py grade-brief <skill> <id> --replies FILE
  maintainer/evals.py record OUT <skill> <id> GRADES
  maintainer/evals.py table SIDE [--against BEFORE_SIDE]
"""

import argparse
import json
import os
import pathlib
import re
import shlex
import sqlite3
import statistics
import subprocess
import sys
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "maintainer"))
import kit_path  # noqa: E402
import transcript  # noqa: E402  knows which user lines the harness injects.
import run_cost  # noqa: E402

EVALS = ROOT / "evals"
# Claude Code writes one <session-id>.jsonl per session at the top of each project folder.
PROJECTS = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude")) / "projects"
FENCED_JSON = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)
# T3 opens each child task's first message with a line naming its delegate_task role, and,
# since late November 2026, opens each message an agent sends with a line naming the sender.
T3_PREFIX = re.compile(r"^Act as the [\w-]+ sub-agent for this task\.\n\n")
T3_SENDER = re.compile(r'^\[T3 Code: the agent in T3 thread "[^"\n]*" sent this message, not the user\.\]\n\n')
# hooks/reply-shape-context.py skips T3 child tasks unless their brief has this line.
REPLY_RULES = "Reply rules: on. This run plays Oliver's own session."
# The files --rules DIR holds, which a side reads in place of the installed reply rules.
RULES_FILES = ("replies.md", "reply-shape/SKILL.md")
# A forked verifier or child sees only its own brief. On Oct 26, 2026 a player called
# verify-work with no arguments, and its verifier ran gh, git fetch, and ssh.
LIMITS = ("Limits: the ones this session states, in this brief or later, if any. Put them in a "
          "`Limits:` line in each verify-work call and child task brief, since those see only what "
          "you pass them.")


class EvalError(Exception):
    pass


def load_scenarios(evals=EVALS):
    """Returns {(skill, id): scenario}, each scenario with its eval folder as `folder`."""
    scenarios = {}
    for path in sorted(evals.glob("*/evals.json")):
        for scenario in json.loads(path.read_text())["scenarios"]:
            scenarios[(scenario["skill"], scenario["id"])] = {**scenario, "folder": str(path.parent)}
    return scenarios


def find(scenarios, skill, scenario_id):
    if (skill, scenario_id) in scenarios:
        return scenarios[(skill, scenario_id)]
    known = ", ".join(f"{s}/{i}" for s, i in scenarios) or "none"
    raise EvalError(f"unknown scenario {skill}/{scenario_id}; known: {known}")


def fill(text, cwd):
    """The text with {cwd} replaced by the trial's cwd, for a preamble or an assertion."""
    return text.replace("{cwd}", str(cwd)) if cwd else text


def rules_line(rules):
    """The brief's first line. None loads the installed reply rules through the hook; a
    folder replaces them with its RULES_FILES, read by the player, and "none" drops them.
    Neither of those starts with "Reply rules: on", so the hook loads nothing."""
    if rules is None:
        return REPLY_RULES
    if rules == "none":
        return "This run plays Oliver's own session, without his reply rules."
    files = " and ".join(str(pathlib.Path(rules, name).resolve()) for name in RULES_FILES)
    return f"Reply rules: read {files} now, and follow them on every reply. This run plays Oliver's own session."


def check_rules(rules):
    if rules not in (None, "none"):
        missing = [name for name in RULES_FILES if not pathlib.Path(rules, name).is_file()]
        if missing:
            raise EvalError(f"--rules {rules} lacks {', '.join(missing)}")
    return rules


def brief(scenario, variants={}, cwd=None, rules=None):
    """The player's task. `cwd` is the trial's resolved cwd, which start passes, and
    `rules` is start's --rules value."""
    if not scenario.get("cwd"):
        raise EvalError(f"{scenario['skill']}/{scenario['id']} has no cwd, so it can't run yet")
    cwd = cwd or scenario["cwd"]
    if not os.path.isabs(cwd):
        raise EvalError(f"{scenario['skill']}/{scenario['id']} has a relative cwd, so only start can brief it")
    lines = [rules_line(rules)]
    for name, folder in variants.items():
        lines.append(
            f"For this whole session, read {pathlib.Path(folder, 'SKILL.md').resolve()} and follow it in place "
            f"of the installed {name} skill."
        )
    if variants:
        # A line in this brief reaches only the player, so a child would load the installed skill.
        lines.append("Copy the lines above, and this one, into the brief of any child task or subagent you start.")
    lines.append(f"Work in {cwd}.")
    if scenario.get("preamble"):
        lines.append(fill(scenario["preamble"], cwd))
    lines += [LIMITS, "", scenario["prompt"]]
    return "\n".join(lines)


def grade_brief(scenario, replies):
    context = [f"Scenario: {scenario['skill']}/{scenario['id']}"]
    # start writes trial.json under OUT/<skill>/<id>/, beside OUT/<skill>/<id>.replies.md.
    trial = load_trial(pathlib.Path(replies).parent.parent, scenario)
    cwd = trial["cwd"] if trial else scenario.get("cwd")
    assertions = "\n".join(f"{n}. {fill(text, cwd)}" for n, text in enumerate(scenario["assertions"], 1))
    if cwd:
        context.append(f"Repo the player worked in: {cwd}")
    if scenario.get("setup"):
        context.append(f"Setup, run from {scenario['folder']}: {setup_command(scenario, cwd)}")
    return f"""Grade one eval run. Read-only: do not edit, commit, or run the scenario again.

{chr(10).join(context)}
Player replies, one `=== turn N ===` section per turn, split by `--- after a harness notice ---` where a notice such as a late child's result woke the player, then the skills the player loaded, the role, interaction mode, and target of each `delegate_task` call it made{', and, under `=== tool calls ===`, every tool call it and its native subagents made, with each result (`<!` marks an error)' if scenario.get('tool_calls') else ''}: {pathlib.Path(replies).resolve()}

Grade each assertion pass or fail against the replies, and quote the evidence. When an
assertion is about the repo's state, inspect the repo read-only.

{assertions}

Return only this JSON object, with one result per assertion:
{{"results": [{{"n": 1, "pass": true, "evidence": "<quote>"}}]}}
"""


NAME = re.compile(r"^name:\s*[\"']?([\w.-]+)", re.MULTILINE)


def variant_names(dirs):
    """Returns {skill name: dir} for each --variant dir, the name from its SKILL.md
    frontmatter."""
    variants = {}
    for folder in dirs:
        skill = pathlib.Path(folder, "SKILL.md")
        if not skill.is_file():
            raise EvalError(f"no SKILL.md in {folder}")
        match = NAME.search(skill.read_text().split("\n---", 1)[0])
        if not match:
            raise EvalError(f"{skill} has no name in its frontmatter")
        if match.group(1) in variants:
            raise EvalError(f"two --variant dirs name the {match.group(1)} skill")
        variants[match.group(1)] = pathlib.Path(folder).resolve()
    return variants


def trial_dir(out, scenario):
    return pathlib.Path(out, scenario["skill"], scenario["id"])


def setup_command(scenario, cwd):
    """The setup line with {cwd} shell-quoted, so a path with spaces stays one argument."""
    return scenario["setup"].replace("{cwd}", shlex.quote(str(cwd)))


def start(out, scenario, variants, rules=None):
    """Runs the scenario's setup for this trial, writes OUT/<skill>/<id>/trial.json (cwd,
    brief, variants, rules), and returns the brief. A relative cwd resolves under that folder, so
    trials of one scenario can run at once."""
    if not scenario.get("cwd"):
        raise EvalError(f"{scenario['skill']}/{scenario['id']} has no cwd, so it can't run yet")
    check_rules(rules)  # before setup, which resets the trial's repo
    folder = trial_dir(out, scenario)
    folder.mkdir(parents=True, exist_ok=True)
    cwd = scenario["cwd"] if os.path.isabs(scenario["cwd"]) else str((folder / scenario["cwd"]).resolve())
    if scenario.get("setup"):
        run = subprocess.run(["bash", "-c", setup_command(scenario, cwd)], cwd=scenario["folder"],
                             capture_output=True, text=True)
        if run.returncode:
            raise EvalError(f"setup exited {run.returncode}: {(run.stderr or run.stdout).strip()[-2000:]}")
    text = brief(scenario, variants, cwd, rules)
    (folder / "trial.json").write_text(json.dumps(
        {"cwd": cwd, "brief": text, "variants": {name: str(path) for name, path in variants.items()},
         "rules": rules},
        indent=2, ensure_ascii=False) + "\n")
    return text


def load_trial(out, scenario):
    """The trial.json that start wrote for this scenario in OUT."""
    path = trial_dir(out, scenario) / "trial.json"
    return json.loads(path.read_text()) if path.is_file() else None


def save_cost(out, scenario, transcript_path):
    """Writes run_cost.measure(transcript_path) as OUT/<skill>/<id>/cost.json."""
    try:
        cost = run_cost.measure(transcript_path)
    except (LookupError, sqlite3.Error, OSError, ValueError) as error:
        raise EvalError(f"no cost for {transcript_path}: {error}") from error
    path = trial_dir(out, scenario) / "cost.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cost, indent=2) + "\n")
    return path


def is_trial(path):
    """Whether start began a trial in this folder or record graded one: <skill>/<id>.json
    or <skill>/<id>/trial.json."""
    return any(path.glob("*/*.json")) or any(path.glob("*/*/trial.json"))


def trial_folders(path):
    """A side's trials: the folder itself when it is one, else each subfolder that is.
    A trial that start began counts, graded or not, so an ungraded one shows as missing."""
    path = pathlib.Path(path)
    if is_trial(path):
        return [path]
    trials = sorted(sub for sub in path.glob("*") if sub.is_dir() and is_trial(sub))
    if not trials:
        raise EvalError(f"no recorded results in {path}")
    return trials


def load_side(path):
    """One (run, costs) pair per trial on a side: the folder itself when it is a trial,
    else each subfolder that is. costs maps each scenario label the trial started or graded
    to its cost.json, or to None when the run saved none."""
    side = []
    for folder in trial_folders(path):
        run = load_run(folder)
        started = {f"{p.parent.parent.name}/{p.parent.name}" for p in pathlib.Path(folder).glob("*/*/trial.json")}
        costs = {}
        for label in sorted(started | {label for label, _ in run}):
            cost = pathlib.Path(folder, label, "cost.json")
            costs[label] = json.loads(cost.read_text()) if cost.is_file() else None
        side.append((run, costs))
    return side


# Claude Code records an interrupt as a user text line, but the user typed nothing.
INTERRUPTED = "[Request interrupted by user"
# Splits a turn's replies where a harness notice woke the player mid-turn.
NOTICE_BREAK = "\n\n--- after a harness notice ---\n"


def messages(path, sent):
    """Yields ("turn", text) for the first message the user sent, then for each that is the
    next of `sent`, the scenario's later turns; ("notice", text) for any other user text,
    such as T3's restart notice, a delegated task's result, or a reminder; ("reply", text)
    for each assistant text; and ("tool", None) for each tool call or result. T3 delivers a
    sent turn word for word, and a notice can say anything a turn can, so only the
    scenario's own list tells them apart. transcript.claude_events already drops
    sidechains; a skill load or compaction summary yields nothing, since a compaction can
    land between the report and a late notice."""
    later, user_line = list(sent), None
    for line, role, text in transcript.claude_events(path):
        if role == "assistant":
            yield "reply", text
        elif role in ("tool", "result", "error"):
            yield "tool", None
        elif role != "user" or text.startswith(INTERRUPTED) or line == user_line:
            continue
        elif user_line is None:
            if not transcript.is_injected(text):
                user_line = line
                yield "turn", text
        elif later and T3_SENDER.sub("", text, count=1).strip() == later[0].strip():
            later.pop(0)
            user_line = line
            yield "turn", text
        else:
            yield "notice", text


def find_transcript(brief_text):
    """Returns the newest top-level transcript whose first user message, after T3's
    prefix, is the brief. An exact match keeps a plain brief from picking a variant run."""
    paths = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        first = next((text for line, role, text in transcript.claude_events(path)
                      if role == "user" and not transcript.is_injected(text)), "")
        if T3_PREFIX.sub("", T3_SENDER.sub("", first, count=1), count=1) == brief_text:
            return path
    raise EvalError(f"no transcript in {PROJECTS} whose first message is this scenario's brief")


def turn_replies(path, sent):
    """Returns, for each turn, the replies the user saw before the next: the last assistant
    text before each notice that came after a reply, then the last before the next turn.
    A notice that arrives after the report, such as a late child's result, so keeps the
    report beside the reply to the notice. A notice after a tool call came mid-work, and
    splits nothing."""
    turns, ended = [], False
    for kind, text in messages(path, sent):
        if kind == "turn":
            turns.append([None])
        elif turns and kind == "reply":
            turns[-1][-1] = text
        elif turns and kind == "notice" and ended:
            turns[-1].append(None)
        ended = kind == "reply"
    if not turns:
        raise EvalError(f"no user message in {path}")
    for n, replies in enumerate(turns, 1):
        if replies[-1] is None:
            replies.pop()
        if not replies:
            raise EvalError(f"turn {n} in {path} has no assistant reply")
    return turns


def delegate_calls(path):
    """The role, interaction mode, and target of each delegate_task call, one JSON line
    each, so the grader can check which child ran on which model and effort."""
    return [json.dumps({key: payload[1].get(key) for key in ("role", "interactionMode", "target")}, sort_keys=True)
            for _, role, payload in transcript.claude_events(path)
            if role == "tool" and (payload[0] or "").endswith("delegate_task")]


TOOL_RESULT_LIMIT = 8000  # keeps probe output whole; cuts a skill file the player read


def tool_calls(path):
    """Each tool call the player and its native subagents made, once, as `> name: input`,
    with its result under it as `<` (`<!` when it errored). A result longer than
    TOOL_RESULT_LIMIT is cut, and the transcript it came from is named, so a grader can
    check that a probe ran instead of trusting the reply. Subagents write their own files
    under <session>/subagents/; only user and assistant rows count, since a request
    snapshot repeats earlier calls."""
    path = pathlib.Path(path)
    lines = []
    for file in [path, *sorted(path.with_suffix("").glob("subagents/**/*.jsonl"))]:
        label = "" if file == path else f"[{file.stem}] "
        calls, results = {}, {}
        for _, record in transcript.records(file):
            content = (record.get("message") or {}).get("content")
            if record.get("type") not in ("user", "assistant") or not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    calls.setdefault(block.get("id"), (block.get("name"), block.get("input") or {}))
                elif block.get("type") == "tool_result":
                    results.setdefault(block.get("tool_use_id"), block)
        for call_id, (name, args) in calls.items():
            if name == "Bash" and isinstance(args.get("command"), str):
                args = args["command"]
            else:
                args = json.dumps(args, ensure_ascii=False)
            lines.append(f"{label}> {name}: {args}")
            result = results.get(call_id)
            if result is None:
                lines.append(f"{label}< (no result)")
                continue
            text = transcript.block_text(result.get("content"))
            if len(text) > TOOL_RESULT_LIMIT:
                text = text[:TOOL_RESULT_LIMIT] + f" …[{len(text) - TOOL_RESULT_LIMIT} more chars in {file}]"
            lines.append(f"{label}{'<!' if result.get('is_error') else '<'} {text}")
    return lines


def save_replies(out, scenario, transcript_path):
    turns = turn_replies(transcript_path, scenario.get("turns", []))
    expected = 1 + len(scenario.get("turns", []))
    if len(turns) != expected:
        raise EvalError(f"expected {expected} turns in {transcript_path}, found {len(turns)}")
    text = "\n\n".join(f"=== turn {n} ===\n" + NOTICE_BREAK.join(reply.strip() for reply in replies)
                       for n, replies in enumerate(turns, 1))
    text += "\n\n=== skills loaded ===\n" + (", ".join(transcript.skills(transcript_path)) or "none")
    calls = delegate_calls(transcript_path)
    if calls:
        text += "\n\n=== delegate_task calls ===\n" + "\n".join(calls)
    if scenario.get("tool_calls"):
        text += "\n\n=== tool calls ===\n" + ("\n".join(tool_calls(transcript_path)) or "none")
    path = pathlib.Path(out, scenario["skill"], f"{scenario['id']}.replies.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    return path


def parse_grades(text, count):
    match = FENCED_JSON.search(text)
    try:
        data = json.loads(match.group(1) if match else text)
    except json.JSONDecodeError as error:
        raise EvalError(f"grades aren't JSON: {error}") from error
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise EvalError('grades need a "results" list')
    if not all(isinstance(r, dict) for r in results):
        raise EvalError("each result must be an object")
    if not all(type(r.get("n")) is int for r in results):
        raise EvalError("each result needs an integer n")
    numbers = sorted(r["n"] for r in results)
    if numbers != list(range(1, count + 1)):
        raise EvalError(f"need one result for each assertion 1..{count}, got n = {numbers}")
    for result in results:
        if not isinstance(result.get("pass"), bool):
            raise EvalError(f"result {result['n']}: pass must be true or false")
        if not isinstance(result.get("evidence"), str) or not result["evidence"].strip():
            raise EvalError(f"result {result['n']}: evidence is empty")
    return sorted(results, key=lambda r: r["n"])


def record(out, scenario, grades_text):
    results = parse_grades(grades_text, len(scenario["assertions"]))
    path = pathlib.Path(out, scenario["skill"], f"{scenario['id']}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"skill": scenario["skill"], "id": scenario["id"], "assertions": scenario["assertions"], "results": results},
        indent=2, ensure_ascii=False,
    ) + "\n")
    return path


def load_run(out):
    """Returns {(scenario label, n): (assertion text, passed)} for one run folder, empty
    for a trial that start began but record never graded."""
    paths = sorted(pathlib.Path(out).glob("*/*.json"))
    if not paths and not any(pathlib.Path(out).glob("*/*/trial.json")):
        raise EvalError(f"no recorded results in {out}")
    run = {}
    for path in paths:
        data = json.loads(path.read_text())
        label = f"{data['skill']}/{data['id']}"
        for result in data["results"]:
            run[(label, result["n"])] = (data["assertions"][result["n"] - 1], result["pass"])
    return run


def short(text, width=60):
    text = text.replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def mark(entry):
    return "—" if entry is None else ("✅" if entry[1] else "❌")


class Trial(NamedTuple):
    name: str  # the side, or <side>/<trial folder>
    run: dict
    costs: dict
    started: list  # the scenario labels start began here, each with a trial.json


def side_trials(name, path):
    folders = trial_folders(path)
    return [Trial(name if folder == pathlib.Path(path) else f"{name}/{folder.name}", run, costs,
                  [label for label in costs if (folder / label / "trial.json").is_file()])
            for folder, (run, costs) in zip(folders, load_side(path))]


def passes(trials, key):
    return sum(1 for trial in trials if trial.run.get(key, (None, False))[1])


def tokens(n):
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k" if n < 10_000 else f"{n / 1000:.0f}k"
    return f"{n / 1_000_000:.1f}M"


def duration(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m {seconds:02d}s"


def cost_lines(sides):
    """The median cost of each side's trials, and a warning for each run with no cost.json
    or an incomplete one. When no run on any side saved a cost, no table, and a warning only
    for each run start began, since results recorded before start have no cost to miss."""
    if not any(cost for _, trials in sides for trial in trials for cost in trial.costs.values()):
        return [], [f"Warning: {trial.name}: no cost.json for {label}"
                    for _, trials in sides for trial in trials for label in trial.started]
    lines = ["| median of trials | wall | input | cache write | cache read | output | USD |", "|" + "---|" * 7]
    warnings = []
    for name, trials in sides:
        totals = []
        for trial in trials:
            for label, cost in trial.costs.items():
                if cost is None:
                    warnings.append(f"Warning: {trial.name}: no cost.json for {label}")
                    continue
                if cost["unpriced"]:
                    warnings.append(f"Warning: {trial.name}: no rate for {', '.join(cost['unpriced'])}, so USD is ?")
                warnings += [f"Warning: {trial.name}: {missing}" for missing in cost["missing"]]
            if any(trial.costs.values()):
                totals.append(run_cost.add(cost for cost in trial.costs.values() if cost))
        if not totals:
            lines.append(f"| {name} |" + " — |" * 6)
            continue
        cells = [name, duration(statistics.median(t["wall_s"] for t in totals))]
        cells += [tokens(round(statistics.median(t["tokens"][kind] for t in totals)))
                  for kind in ("input", "cache_write", "cache_read", "output")]
        cells.append("?" if any(t["usd"] is None for t in totals)
                     else f"${statistics.median(t['usd'] for t in totals):.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    return lines, warnings


def table(out, against=None):
    """Returns (Markdown table plus summary line, regressions). Each folder is a side of one
    or more trials. When both sides have one, cells show ✅ or ❌; otherwise each shows how
    many trials passed, and a flip is an assertion every before trial passed and some after
    trial didn't. A result some trial on any side graded and another trial lacks, whether
    it began the scenario or not, is a regression too, as missing on the lacking side, with
    or without a before side."""
    after = side_trials("after" if against else "result", out)
    before = side_trials("before", against) if against else None
    sides = ([("before", before)] if before else []) + [("after" if against else "result", after)]
    many = any(len(trials) > 1 for _, trials in sides)
    keys = sorted({key for _, trials in sides for trial in trials for key in trial.run})
    header = ["scenario", "#", "assertion"] + [f"{name} ({len(trials)})" if many else name for name, trials in sides]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    regressions, changed, everywhere = [], [], 0
    for key in keys:
        texts = [trial.run[key][0] for trial in after if key in trial.run]
        old = [trial.run[key][0] for trial in before or [] if key in trial.run]
        cells = [key[0], str(key[1]), short((texts or old)[0])]
        everywhere += passes(after, key) == len(after)
        # Every trial on every side must grade what any trial graded, or the pass counts differ in base.
        missing = {side: any(key not in trial.run for trial in trials) for side, trials in sides}
        flip = False
        if before is not None:
            if texts and old and texts[0] != old[0]:
                changed.append(f"{key[0]} #{key[1]}")
            flip = not any(missing.values()) and passes(before, key) == len(before) and passes(after, key) < len(after)
        if any(missing.values()) or flip:
            where = " and ".join(side for side, lacks in missing.items() if lacks)
            label = "" if where == sides[-1][0] else f" {where}"
            regressions.append(f"{key[0]} #{key[1]}"
                               + (f" (missing{label})" if where else " (flip)" if many else ""))
        for side, trials in sides:
            cells.append(f"{passes(trials, key)}/{len(trials)}" if many else mark(trials[0].run.get(key)))
            if many and missing.get(side):
                cells[-1] += " ⚠ missing"
        if many and flip:
            cells[-1] += " ⚠ flip"
        lines.append("| " + " | ".join(cells) + " |")
    # A scenario no trial graded has no assertion numbers, so it has no row.
    graded = {label for label, _ in keys}
    regressions += [f"{label} (missing)" for label in sorted(
        {label for _, trials in sides for trial in trials for label in trial.costs} - graded)]
    if many:
        summary = f"{everywhere}/{len(keys)} pass in every trial"
    else:
        summary = f"{sum(1 for _, ok in after[0].run.values() if ok)}/{len(keys)} pass"
    if before is not None or regressions:
        noun = "regression" if len(regressions) == 1 else "regressions"
        summary = f"{'after: ' if before is not None else ''}{summary} · {len(regressions)} {noun}"
        if regressions:
            summary += ": " + ", ".join(regressions)
    costs, warnings = cost_lines(sides)
    if many and before is not None:
        warnings += [f"Warning: {name} has 1 trial; a flip needs 2 or more a side to mean much"
                     for name, trials in sides if len(trials) < 2]
    if changed:
        warnings.append("Warning: assertion text changed between runs: " + ", ".join(changed))
    blocks = ["\n".join(lines)] + ["\n".join(block) for block in (costs, warnings) if block]
    return "\n\n".join(blocks + [summary]), regressions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("skill", nargs="?")
    for name in ("start", "turns", "grade-brief", "replies"):
        command = commands.add_parser(name)
        command.add_argument("skill")
        command.add_argument("id")
    for name in ("start", "replies"):
        commands.choices[name].add_argument("out")
    commands.choices["start"].add_argument("--variant", action="append", default=[])
    commands.choices["start"].add_argument("--rules")
    commands.choices["replies"].add_argument("--transcript")
    commands.choices["grade-brief"].add_argument("--replies", required=True)
    recording = commands.add_parser("record")
    for name in ("out", "skill", "id", "grades"):
        recording.add_argument(name)
    tabling = commands.add_parser("table")
    tabling.add_argument("out")
    tabling.add_argument("--against")
    args = parser.parse_args(argv)

    try:
        scenarios = load_scenarios()
        if args.command == "list":
            matching = [s for s in scenarios.values() if args.skill in (None, s["skill"])]
            if args.skill and not matching:
                known = ", ".join(sorted({s for s, _ in scenarios}))
                raise EvalError(f"unknown skill {args.skill}; known: {known}")
            for s in matching:
                turns = len(s.get("turns", []))
                print(f"{s['skill']}/{s['id']} · {turns} turn{'' if turns == 1 else 's'} · {len(s['assertions'])} assertions")
        elif args.command == "table":
            text, regressions = table(args.out, args.against)
            print(text)
            return 1 if regressions else 0
        else:
            scenario = find(scenarios, args.skill, args.id)
            if args.command == "start":
                print(start(args.out, scenario, variant_names(args.variant), args.rules))
            elif args.command == "turns":
                print(json.dumps(scenario.get("turns", []), indent=2, ensure_ascii=False))
            elif args.command == "replies":
                if args.transcript and not pathlib.Path(args.transcript).is_file():
                    raise EvalError(f"no transcript at {args.transcript}")
                trial = load_trial(args.out, scenario)
                if not args.transcript and not trial:
                    raise EvalError(f"no trial.json for {args.skill}/{args.id} in {args.out}; begin the run with start")
                # Each trial's brief names its own cwd, so parallel trials can't pick each other's transcript.
                transcript_path = args.transcript or find_transcript(trial["brief"])
                print(transcript_path)
                print(save_replies(args.out, scenario, transcript_path))
                print(save_cost(args.out, scenario, transcript_path))
            elif args.command == "grade-brief":
                print(grade_brief(scenario, args.replies), end="")
            else:
                grades = pathlib.Path(args.grades)
                if not grades.is_file():
                    raise EvalError(f"no grades file at {grades}")
                print(record(args.out, scenario, grades.read_text()))
    except EvalError as error:
        print(f"evals.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

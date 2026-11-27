#!/usr/bin/env python3
"""Edits a coordinator project's project.md (references/project.md says what each
section holds), so the coordinator never patches it by hand. Every edit leaves the rest
of the file byte for byte and replaces the file atomically.

  project.py DIR init --project P --coordinator LINK --checkout PATH --mode M --goal G --proof P
  project.py DIR decide TEXT        add `- <date> · TEXT` under Decisions
  project.py DIR learn TEXT         add `- <date> · TEXT` under Learnings
  project.py DIR worker SLUG [--thread T] [--pr B] [--state S] [--waits W] [--last L] [--issue I]
                                    set a Workers row's columns, adding the row if it's new;
                                    --issue adds the Issue column to a table without it
  project.py DIR listen KEY VALUE   set `- KEY: VALUE` under Listening
  project.py DIR queue add KIND NAME [--from F]
                                    queue an item that waits on the user (KIND: stuck,
                                    decide, review, or do), then print the queue
  project.py DIR queue done ID --answer A
                                    take the item off the queue, adding it, who asked, and
                                    the answer A (the pick in words and the user's own)
                                    under Decisions, then print the queue
  project.py DIR queue show         print the strip and need a reply shows, and every item
  project.py DIR queue import [--from ID=F] [--stuck ID]
                                    start the Queue of a project from before it: queue each
                                    item, needs then standing, that the turn block on
                                    standard input names (a reply, or its block alone),
                                    item ID asked by F, or a stuck run
  project.py DIR phase SLUG --result R (--goal G --proof P | --park REASON)
                                    end the running phase: save project.md to
                                    phases/<NN>-SLUG.md, add its line under Phases, reset
                                    the phase's sections, then start the next or park
  project.py DIR start --goal G --proof P
                                    start the next phase on a parked project
  project.py DIR tick [--send]      print what changed since the last tick that T3 doesn't
                                    report; --send messages it to the coordinator's thread
                                    and saves DIR/tick.json, while Heartbeat is `tick`
  project.py DIR status [--json] [--html] [--no-live]
                                    the project's overview (references/status.md), reading thread,
                                    PR, and check state live: --json prints status_data's data;
                                    --html writes it into a copy of scripts/status.html in the
                                    temp folder and prints that file's path; both print the data
                                    with the path as `html_path`; --no-live skips t3 and gh.
                                    Takes at least one of --json and --html. Never writes DIR

TEXT, VALUE, or A `-` reads standard input. A row's Worker cell is SLUG, or SLUG followed by ` (`
and a label. State starts with one of STATES; detail may follow, as in
`done: #12 MERGED`. Exits 2 on a usage error and 1 on a file it can't edit."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import project_md
import project_queue
import turn_block

STATES = ("queued", "overdue", "unknown", "running", "waiting", "stuck", "done", "dropped",
          "replaced by <worker>", "absorbed into <worker>")
STATE = re.compile(r"(queued|overdue|unknown|running|waiting|stuck|done|dropped)\b|(replaced by|absorbed into) \S")
COLUMNS = {"thread": "Thread", "pr": "Branch or PR", "state": "State", "waits": "Waits on", "last": "Last side effect",
           "issue": "Issue"}  # Issue is optional: `worker --issue` adds it to a table without it

SKELETON = """# ◆ {project}

Coordinator: {coordinator} · Checkout: {checkout} · Mode: {mode}

## Goal

{goal}
Proof: {proof}
Follow-ups: none

## Queue

Next id: 1

| # | Kind | Name | From | Since |
|---|---|---|---|---|

## Decisions

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|

## Learnings

## Listening

- Heartbeat: none
- Startup: none
- Watches: none
"""


class ProjectError(Exception):
    pass


def imported(lines: list[str], text: str, sources: dict[int, str] | None = None,
             stuck: list[int] | tuple[int, ...] = ()) -> list[project_queue.Item]:
    """Starts the Queue of a project from before it, holding each user item the turn block
    in text names: needs, then standing, in id order, which is the order they arose. Text is
    a reply ending in its block, or the block's JSON alone. sources names who asked an item,
    by its id in the block, else `coordinator`, and an id in stuck queues a stuck run, which
    a turn block can't say. Refuses a project that has a Queue, so a second import can't
    queue a call twice."""
    sources = sources or {}
    if project_queue.read(lines) is not None:
        raise ProjectError("the Queue exists: add a call to it with `queue add`")
    block = f"<!-- turn {text.strip()} -->" if text.lstrip().startswith("{") else text
    try:
        items = sorted(turn_block.parse(block).items, key=lambda need: need.id)
    except turn_block.Malformed as error:
        raise ProjectError(f"queue import takes a turn block on standard input, a reply ending in one or its JSON: {error}")
    if unknown := sorted({*sources, *stuck} - {need.id for need in items}):
        raise ProjectError(f"the turn block has no item {', '.join(map(str, unknown))}")
    project_queue.create(lines)
    # A turn block's name may run over lines; a queue row holds one line, so each line break,
    # with the spaces around it, becomes one space, and the rest of the name stays as written.
    return [project_queue.add(lines, "stuck" if need.id in stuck else need.kind,
                              re.sub(r"[ \t]*(?:\r\n|\r|\n)[ \t]*", " ", need.name), sources.get(need.id, "coordinator"))
            for need in items]


def queue(lines: list[str], action: str, *, kind: str | None = None, name: str | None = None,
          source: str | None = None, ident: int | None = None, answer: str | None = None,
          block: str | None = None, sources: list[str] | None = None, stuck: list[int] | None = None) -> str:
    """Runs a `queue` action on lines and returns what it prints: the queue as `show` gives
    it, after a line naming the item an add or done touched. `done` records the item, who
    asked it, and the answer under Decisions, so a resolved call keeps its trail."""
    try:
        if action == "add":
            item = project_queue.add(lines, kind, name, source or "coordinator")
            head = [f"queued {item.id}: {item.kind} · {item.name}"]
        elif action == "done":
            if not (answer or "").strip():
                raise ProjectError("--answer takes the answer: the pick in words and the user's own")
            item = project_queue.done(lines, ident)
            decide(lines, f"{item.source} asked: {item.name} (queue {item.id}, {item.kind}) → {answer.strip()}")
            head = [f"done {item.id}: {item.kind} · {item.name}"]
        elif action == "import":
            asked = {}
            for pair in sources or []:
                ident_text, sep, asker = pair.partition("=")
                if not (sep and ident_text.strip().isdigit() and asker.strip()):
                    raise ProjectError(f"--from takes ID=WHO, as in 64=\"R153 <thread link>\", not {pair!r}")
                asked[int(ident_text)] = asker.strip()
            head = [f"imported {item.id}: {item.kind} · {item.name}"
                    for item in imported(lines, block or "", asked, stuck or ())]
        else:
            head = []
        return "\n".join([*head, project_queue.show(project_queue.read(lines))])
    except project_queue.QueueError as error:
        raise ProjectError(str(error))


def _section(lines: list[str], name: str) -> tuple[int, int]:
    """The index of `## name` and the index where its section ends."""
    try:
        start = lines.index(f"## {name}")
    except ValueError:
        raise ProjectError(f"no `## {name}` section")
    return start, _end(lines, start)


def _insert(lines: list[str], name: str, line: str) -> None:
    """Puts `line` after the section's last non-blank line, keeping a blank line before
    the next heading."""
    start, end = _section(lines, name)
    at = next(i for i in range(end - 1, start - 1, -1) if lines[i].strip()) + 1
    added = [line] if at > start + 1 else ["", line]
    if at < len(lines) and lines[at].startswith("## "):
        added.append("")
    lines[at:at] = added


def _bullet(text: str) -> str:
    """text as one list item: every line ending, CRLF and a lone CR too, as an indented
    line, so no line of it reads as a heading or a row of its own."""
    return "- " + text.replace("\r\n", "\n").replace("\r", "\n").strip().replace("\n", "\n  ")


_cells = project_md.cells


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _dated(text: str) -> str:
    if not text.strip():
        raise ProjectError("empty text")
    return _bullet(f"{date.today().isoformat()} · {text.strip()}")


def decide(lines: list[str], text: str) -> None:
    _insert(lines, "Decisions", _dated(text))


def learn(lines: list[str], text: str) -> None:
    _insert(lines, "Learnings", _dated(text))


def worker(lines: list[str], slug: str, **columns: str | None) -> None:
    state = columns.get("state")
    if state is not None and not STATE.match(state):
        raise ProjectError(f"state {state!r} doesn't start with one of: {', '.join(STATES)}")
    for value in [slug, *(v for v in columns.values() if v is not None)]:
        if "\n" in value or not value.strip():
            raise ProjectError(f"a cell is one non-empty line: {value!r}")
    start, end = _section(lines, "Workers")
    table = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if len(table) < 2:
        raise ProjectError("no Workers table")
    header = _cells(lines[table[0]])
    if columns.get("issue") is not None and COLUMNS["issue"] not in header:  # a table from before the column
        for i, ending in zip(table, [f" {COLUMNS['issue']} |", "---|", *["  |"] * (len(table) - 2)]):
            lines[i] = lines[i].rstrip() + ending
        header.append(COLUMNS["issue"])
    rows = [i for i in table[2:] if (first := _cells(lines[i])[0]) == slug or first.startswith(f"{slug} (")]
    if len(rows) > 1:
        raise ProjectError(f"{len(rows)} Workers rows match {slug!r}")
    if not rows and state is None:  # most likely a mistyped slug
        raise ProjectError(f"no Workers row matches {slug!r}: a new row needs --state")
    cells = _cells(lines[rows[0]]) if rows else [slug] + ["—"] * (len(header) - 1)
    if len(cells) != len(header):  # a hand edit dropped or split a cell: which one is a guess
        raise ProjectError(f"the {slug!r} row has {len(cells)} cells and the header {len(header)}: fix it by hand")
    for key, value in columns.items():
        if value is not None:
            if COLUMNS[key] not in header:
                raise ProjectError(f"the Workers table has no {COLUMNS[key]!r} column")
            cells[header.index(COLUMNS[key])] = value.strip().replace("|", "\\|")
    if rows:
        lines[rows[0]] = _row(cells)
    else:
        lines.insert(table[-1] + 1, _row(cells))


def listen(lines: list[str], key: str, value: str) -> None:
    start, end = _section(lines, "Listening")
    if not key.strip() or ":" in key or not value.strip() or "\n" in value.strip():
        raise ProjectError("listen takes a KEY without a colon and a one-line VALUE")
    line = _bullet(f"{key}: {value.strip()}")
    found = [i for i in range(start + 1, end) if lines[i].startswith(f"- {key}:")]
    if found:
        lines[found[0]] = line
    else:
        _insert(lines, "Listening", line)


FINAL = re.compile(r"(done|dropped)\b|(replaced by|absorbed into) \S")  # the end states in STATE
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PARKED = "Parked "  # a parked Goal's first line: `Parked <date>: <reason>`


def phase(lines: list[str], archive: str, result: str, *,
          goal: str | None = None, proof: str | None = None, park: str | None = None) -> None:
    """Ends the running phase whose snapshot is at `archive` (`phases/<NN>-<slug>.md`): adds
    `- <date> · <NN-slug>: RESULT · ARCHIVE` under Phases, creating it after Goal; empties
    Decisions and Learnings; removes each Result section; drops Workers rows in a FINAL
    state; then writes Goal as GOAL and `Proof: PROOF`, or as `Parked <date>: PARK`, keeping
    its Follow-ups. Refuses a parked project, and needs goal and proof, or park alone."""
    if _parked(lines):
        raise ProjectError("the project is parked: start its next phase with start")
    if (goal is None or proof is None) == (park is None):
        raise ProjectError("a phase ends with a goal and a proof, or with park alone")
    today = date.today().isoformat()
    body = [f"{PARKED}{today}: {_line('park', park)}"] if park is not None else _next(goal, proof)
    line = f"- {today} · {Path(archive).stem}: {_line('result', result)} · {archive}"
    while (heading := next((i for i, text in enumerate(lines)
                            if text == "## Result" or text.startswith("## Result (")), None)) is not None:
        del lines[heading:_end(lines, heading)]
    for name in ("Decisions", "Learnings"):
        if f"## {name}" in lines:
            start_at, end = _section(lines, name)
            lines[start_at + 1:end] = [""]
    _drop_final(lines)
    _goal(lines, body)
    if "## Phases" in lines:
        _insert(lines, "Phases", line)
    else:
        at = _section(lines, "Goal")[1]
        lines[at:at] = ["## Phases", "", line, ""]


def start(lines: list[str], goal: str, proof: str) -> None:
    """Starts the next phase on a parked project: Goal becomes GOAL and `Proof: PROOF`,
    keeping its Follow-ups. Refuses a project whose phase is running."""
    if not _parked(lines):
        raise ProjectError("the project's phase is running: end it with phase")
    _goal(lines, _next(goal, proof))


def _end(lines: list[str], start: int) -> int:
    return next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))


def _line(name: str, value: str) -> str:
    if not value.strip() or "\n" in value.strip() or "\r" in value:
        raise ProjectError(f"--{name} takes one non-empty line")
    return value.strip()


def _next(goal: str, proof: str) -> list[str]:
    return [_line("goal", goal), f"Proof: {_line('proof', proof)}"]


def _parked(lines: list[str]) -> bool:
    """Goal opens with `phase`'s parked line, `Parked <date>: `, and has no `Proof:` above its
    Follow-ups, so a running goal that happens to start with the word stays running."""
    start_at, end = _section(lines, "Goal")
    body = lines[start_at + 1:end]
    body = body[:next((i for i, text in enumerate(body) if text.startswith("Follow-ups:")), len(body))]
    first = next((text for text in body if text.strip()), "")
    return (re.match(rf"{PARKED}\d{{4}}-\d\d-\d\d: ", first) is not None
            and not any(text.startswith("Proof:") for text in body))


def _goal(lines: list[str], body: list[str]) -> None:
    """Replaces Goal's body with `body` and its Follow-ups: the `Follow-ups:` line and the
    lines after it up to Goal's next `###` subheading or its end, or `Follow-ups: none`."""
    start_at, end = _section(lines, "Goal")
    at = next((i for i in range(start_at + 1, end) if lines[i].startswith("Follow-ups:")), None)
    follow_ups = ["Follow-ups: none"]
    if at is not None:
        stop = next((i for i in range(at + 1, end) if lines[i].startswith("### ")), end)
        while not lines[stop - 1].strip():
            stop -= 1
        follow_ups = lines[at:stop]
    lines[start_at + 1:end] = ["", *body, *follow_ups, ""]


def _drop_final(lines: list[str]) -> list[str]:
    """Drops Workers rows whose State is FINAL. A row whose cells don't match the header
    stays, since its State is a guess, and its Worker cell is returned."""
    if "## Workers" not in lines:
        return []
    start_at, end = _section(lines, "Workers")
    table = [i for i in range(start_at + 1, end) if lines[i].startswith("|")]
    header = _cells(lines[table[0]]) if table else []
    if len(table) < 2 or COLUMNS["state"] not in header:
        return []
    state = header.index(COLUMNS["state"])
    unread = []
    for i in reversed(table[2:]):
        cells = _cells(lines[i])
        if len(cells) != len(header):
            unread.insert(0, cells[0] if cells else lines[i])
        elif FINAL.match(cells[state]):
            del lines[i]
    return unread


def _archive(folder: Path, snapshot: bytes, slug: str) -> str:
    """Writes `snapshot` to `phases/<NN>-<slug>.md` under `folder`, NN one past the highest
    there, from 01, never overwriting. A file there that already holds these bytes, left
    by a run whose project.md write failed, is reused. Returns the path from `folder`."""
    phases = folder / "phases"
    phases.mkdir(exist_ok=True)
    numbered = [(m, p) for p in phases.iterdir() if (m := re.match(r"(\d+)-(.+)\.md\Z", p.name))]
    for match, path in numbered:
        if match.group(2) == slug and path.read_bytes() == snapshot:
            os.chmod(path, path.stat().st_mode & (folder / "project.md").stat().st_mode)
            return f"phases/{path.name}"
    name = f"{max((int(m.group(1)) for m, _ in numbered), default=0) + 1:02d}-{slug}.md"
    handle, tmp = tempfile.mkstemp(dir=phases, prefix=".phase.")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(snapshot)
        os.chmod(tmp, (folder / "project.md").stat().st_mode)  # no wider than its source
        os.link(tmp, phases / name)  # fails if the name exists, where os.replace would overwrite it
    finally:
        os.unlink(tmp)
    return f"phases/{name}"


# The tick: the machine's timer runs `tick --send` every 10 minutes (references/tick.md), so
# the coordinator's model wakes only for news T3 doesn't deliver. A heartbeat that woke it
# hourly took no action on 91% of its turns.
ACTIVE = {"preparing", "queued", "starting", "running", "waiting"}  # T3's run statuses still under way
PR_ROW = re.compile(r"(running|overdue|unknown|waiting|stuck)\b")  # a row whose PR is still open work
LINK, PR_REF, THREAD_ROW = project_md.LINK, project_md.PR_REF, project_md.THREAD_ROW
REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
STALL = 3600  # seconds with no new thread item before a running worker counts as stalled
REPEAT = 3600  # a finding still true this long after it was sent is sent again
TIMER_STAMP = ".tick"  # touched in the orchestrate folder by scripts/tick.sh on each run


def _run(args: list[str], cwd: Path | None = None, stdin: str | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, done.stdout if done.returncode == 0 else done.stderr


def _warn(text: str) -> None:
    """A line for the timer's log, which has no times of its own, stamped in UTC."""
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {text}", file=sys.stderr)


def show_thread(thread: str) -> dict | None:
    """The thread's state from `t3 thread show`, or None when it can't be read, with the
    CLI's reason in the log."""
    code, out = _run(["t3", "thread", "show", thread, "--json", "--messages", "0"])
    try:
        return json.loads(out)["thread"] if code == 0 else None
    except (ValueError, KeyError, TypeError):
        return None
    finally:
        if code:
            _warn(f"tick: `t3 thread show {thread}` exited {code}: {(out.strip().splitlines() or [''])[-1][:200]}")


def this_environment() -> str:
    """This machine's T3 environment id, or "" when unknown."""
    path = Path(os.environ.get("T3CODE_HOME", "~/.t3")).expanduser() / "userdata" / "environment-id"
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def view_pr(ref: str) -> list | None:
    """[state, isDraft] of `owner/repo#N`; None when unread."""
    repo, number = ref.split("#")
    code, out = _run(["gh", "pr", "view", number, "-R", repo, "--json", "state,isDraft"])
    if code:
        _warn(f"tick: `gh pr view {number} -R {repo}` exited {code}: {(out.strip().splitlines() or [''])[-1][:200]}")
    try:
        pr = json.loads(out) if code == 0 else None
        return [pr["state"], pr["isDraft"]] if pr else None
    except (ValueError, KeyError, TypeError):
        return None


def _pr(ref: str) -> dict | None:
    """{title, state, isDraft} of `owner/repo#N` for status; None when unread. view_pr
    stays [state, isDraft], since tick compares that value whole."""
    repo, number = ref.split("#")
    code, out = _run(["gh", "pr", "view", number, "-R", repo, "--json", "title,state,isDraft"])
    if code:
        _warn(f"status: `gh pr view {number} -R {repo}` exited {code}: {(out.strip().splitlines() or [''])[-1][:200]}")
    try:
        pr = json.loads(out) if code == 0 else None
        return {key: pr[key] for key in ("title", "state", "isDraft")} if pr else None
    except (ValueError, KeyError, TypeError):
        return None


def _checks(ref: str) -> dict[str, int] | None:
    """The count of `owner/repo#N`'s checks per gh bucket (pass, fail, pending, skipping,
    cancel), {} when it has none, None when unread. With --json, gh exits 0 while checks
    are pending, and 1 with `no checks reported` when there are none."""
    repo, number = ref.split("#")
    code, out = _run(["gh", "pr", "checks", number, "-R", repo, "--json", "bucket"])
    if code and "no checks reported" in out:
        return {}
    try:
        counts: dict[str, int] = {}
        for check in json.loads(out) if code == 0 else None:
            counts[check["bucket"]] = counts.get(check["bucket"], 0) + 1
        return counts
    except (ValueError, KeyError, TypeError):
        _warn(f"status: `gh pr checks {number} -R {repo}` exited {code}: {(out.strip().splitlines() or [''])[-1][:200]}")
        return None


def _header(lines: list[str], field: str) -> str:
    """A `Field: value` from the line under the title, up to the next ` · `."""
    line = next((text for text in lines if text.startswith("Coordinator:")), "")
    match = re.search(rf"(?:^| · ){field}: (.*?)(?= · |$)", line)
    return match.group(1).strip() if match else ""


def _workers(lines: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """The Workers rows as {column: cell}, and the rows whose cells don't match the header."""
    return project_md.workers(lines, *_section(lines, "Workers"))


def _listened(lines: list[str], key: str) -> str:
    start, end = _section(lines, "Listening")
    return next((lines[i][len(f"- {key}:"):].strip() for i in range(start + 1, end)
                 if lines[i].startswith(f"- {key}:")), "")


PR_LINK = re.compile(r"\]\(<?(https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+)>?[^)]*\)")  # a Markdown link to a PR, from its `](`


CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")  # a Markdown code span: a backtick run, closed by one as long


def _unlabel(text: str) -> str:
    """text with each Markdown link to a PR replaced by its URL. The label runs back from
    the link's `](` to its matching `[`, as CommonMark reads it: brackets nest, a
    backslash escapes one, and one inside a code span doesn't count."""
    code = {i for span in CODE_SPAN.finditer(text) for i in range(*span.span())}
    out, at = [], 0
    for match in PR_LINK.finditer(text):
        depth, start = 0, None
        for i in range(match.start(), at - 1, -1):
            escaped = (len(text[:i]) - len(text[:i].rstrip("\\"))) % 2
            if text[i] in "[]" and not escaped and i not in code:
                depth += 1 if text[i] == "]" else -1
                if depth == 0:
                    start = i
                    break
        if start is not None:
            out += [text[at:start], match.group(1)]
            at = match.end()
    return "".join(out) + text[at:]


def _pr_refs(text: str, origin: str, refs: set[str]) -> None:
    """Adds each PR the text names to refs as `owner/repo#N`: `#N` and `repo#N` resolve
    against the checkout's origin, `owner/repo`, and a range `#20–#22` names each PR in
    it. Without an origin, `#N` becomes `?#N` and `repo#N` `?/repo#N`, which tick reports. A `none` Watches value names none."""
    if text.startswith("none"):
        return
    text = project_md.ranges(_unlabel(text))  # a link's label `[#7, …]` names its URL's PR, not #7 here
    owner = origin.split("/")[0] if origin else "?"
    for url_repo, url_n, repo, n, local in PR_REF.findall(text):
        repo = url_repo or (repo if not repo or "/" in repo else f"{owner}/{repo}") or origin or "?"
        refs.add(f"{repo}#{url_n or n or local}")


def _checkout(lines: list[str]) -> Path | None:
    """The Checkout field's directory: the path as written, or, when that isn't a
    directory, without a trailing note such as ` (on `main`)`. None when it's empty."""
    value = _header(lines, "Checkout")
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else Path(re.sub(r" \([^()]*\)$", "", value)).expanduser()


def _origin(checkout: Path | None) -> str:
    """`owner/repo` of the checkout's GitHub origin, or ""."""
    code, out = _run(["git", "-C", str(checkout), "remote", "get-url", "origin"]) if checkout else (1, "")
    match = REMOTE.search(out) if code == 0 else None
    return match.group(1).removesuffix(".git") if match else ""


def _when(stamp: str | None) -> float | None:
    """Seconds since the epoch for T3's ISO time, or None."""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() if stamp else None
    except ValueError:
        return None


def tick(lines: list[str], state: dict, now: float, show=show_thread, view=view_pr,
         hold: bool = True) -> tuple[list[tuple[str, str]], dict] | None:
    """What changed since the last tick that T3 doesn't tell the coordinator, as (key, line)
    pairs due to send, and the state to save once they're sent; None when the coordinator's
    thread can't be read or is archived. While it runs, threads are still read, so a stop or
    a stall is timed from when it happened, but nothing is due and PRs wait, so its own turn
    settles first; hold=False, for a dry run, checks as if it were idle. A read that fails
    is named on stderr, which the timer logs. A row's thread is news when
    it stopped, or has a question, through two ticks while its row says running, since a
    completion T3 delivers gets its row fixed by then; when it runs with no new item for
    STALL since its `updatedAt`; or when it's on another machine, which `t3 thread show` can't read. Each of
    these repeats every REPEAT until its row changes. A PR on an open row or under Watches
    is news once when it merges, closes, reopens, or turns ready or draft against what the
    tick last saw, and a merged or closed PR still under Watches repeats like a row: T3's watch sends
    checks, comments, reviews, and conflicts, not those."""
    coordinator = LINK.search(_header(lines, "Coordinator"))
    lead = coordinator and show(coordinator.group(2))
    if not lead or lead.get("archived"):
        _warn(f"tick: can't read the coordinator's thread, or it's archived: {_header(lines, 'Coordinator')}")
        return None
    busy = hold and lead.get("status") in ACTIVE
    origin = _origin(_checkout(lines))
    seen, threads, prs, found = state.get("threads", {}), {}, {}, []
    watched: set[str] = set()
    _pr_refs(_listened(lines, "Watches"), origin, watched)
    refs = set(watched)
    rows, odd = _workers(lines)
    for line in odd:
        if any(re.match(r"(running|overdue|unknown|waiting)\b", cell) for cell in _cells(line)):  # a cell that opens with a state
            first = (_cells(line) or ["?"])[0]
            found.append((f"odd:{first}", f"{first}: its row's cells don't match the Workers header, so the tick "
                                          "can't read it"))
    for row in rows:
        slug, row_state = row.get("Worker", "?"), row.get(COLUMNS["state"], "")
        if PR_ROW.match(row_state):
            _pr_refs(row.get(COLUMNS["pr"], ""), origin, refs)
        link = LINK.search(row.get(COLUMNS["thread"], ""))
        if not THREAD_ROW.match(row_state):
            continue
        if not link:
            found.append((f"unlinked:{slug}", f"{slug}: its row says {row_state} but has no thread link to check"))
            continue
        place, thread = link.groups()
        if place != coordinator.group(1):
            found.append((f"remote:{thread}", f"{slug}: its thread is on another machine, so read its status with "
                                              f"`t3_thread_read` and environmentId {place}"))
            continue
        now_seen = show(thread)
        if now_seen is None:
            _warn(f"tick: can't read thread {thread}")
            if thread in seen:
                threads[thread] = seen[thread]  # keep its last look, so a stall stays timed
            found.append((f"unread:{thread}", f"{slug}: `t3 thread show` can't read its thread"))
            continue
        before = seen.get(thread, {})
        status, runs, items = now_seen.get("status"), now_seen.get("runCount"), now_seen.get("itemCount")
        asked = now_seen.get("pendingRequestCount") or 0
        # The item count dates activity; updatedAt, which metadata such as a title also moves,
        # dates only a new count or the first look.
        since = before["since"] if before.get("items") == items and "since" in before else (
            _when(now_seen.get("updatedAt")) or now)
        threads[thread] = {"status": status, "runs": runs, "items": items, "asked": asked, "since": since, "at": now}
        held = before.get("status") == status and before.get("runs") == runs  # the same for a whole tick
        if status not in ACTIVE and held:
            found.append((f"ended:{thread}:{runs}", f"{slug}: its thread stopped ({status}) while its row says {row_state}"))
        elif asked and held and before.get("asked") == asked:
            found.append((f"asked:{thread}:{asked}", f"{slug}: its thread waits on {asked} question(s) its row doesn't show"))
        elif status == "running" and now - since >= STALL:
            found.append((f"stalled:{thread}:{items}", f"{slug}: no new thread item in {int((now - since) // 60)} min"))
    for ref in sorted(ref for ref in refs if ref.startswith("?")):
        refs.discard(ref)
        found.append((f"owner:{ref}", f"{ref.lstrip('?/')}: the tick can't tell its repo from the checkout's origin, so "
                                      "write it as owner/repo#N"))
    if busy:
        return [], {**state, "threads": threads}
    events, read_at = [], dict(state.get("prsAt", {}))
    for ref in sorted(refs):
        known = state.get("prs", {}).get(ref)
        prs[ref] = view(ref) or known
        if prs[ref] is not known:
            read_at[ref] = now
        else:
            _warn(f"tick: can't read PR {ref}")
        if ref in watched and prs[ref] and prs[ref][0] != "OPEN":  # a watch left on a finished PR
            found.append((f"watch:{ref}", f"{ref}: {prs[ref][0].lower()}, and still under Watches"))
        elif known and prs[ref] != known:
            change = ({"OPEN": "reopened"}.get(prs[ref][0], prs[ref][0].lower()) if prs[ref][0] != known[0]
                      else "turned draft" if prs[ref][1] else "marked ready")
            events.append((f"pr:{ref}", f"{ref}: {change}"))
    sent = {key: at for key, at in state.get("sent", {}).items() if key in {k for k, _ in found}}
    due = [(key, line) for key, line in found if now - sent.get(key, 0) >= REPEAT] + events
    sent.update({key: now for key, _ in due if not key.startswith("pr:")})
    kept = {**state.get("prs", {}), **{k: v for k, v in prs.items() if v}}  # a PR that leaves and returns isn't new
    return due, {"threads": threads, "prs": kept, "prsAt": {ref: at for ref, at in read_at.items() if ref in kept},
                 "sent": sent}


STALE = 1200  # seconds: tick data older than this reads stale, as _tick's timer warning does


def snapshot(folder: Path) -> dict:
    """One project's card for the live status page (status_server.py), from folder/project.md
    and folder/tick.json alone: status_data(live=False), with each unit's `thread_status`
    and each PR's `state` and `draft` filled from what the tick last saw, where it holds
    them, and asOf.tick when the oldest of those was read. Never raises: a project.md it
    can't read or parse gives an `unknown` card with the reason, and a tick.json it can't,
    a card with no tick data (asOf.tick None).

        Card = {folder, state: "ok", data: status_data, phase: "active" | "parked" | "closed"
                  | "unknown", asOf: {project: mtime, tick: time | None}, tickOn: bool}
             | {folder, state: "unknown", error: str, asOf: {project: mtime | None, tick: mtime | None}}

    phase is parked by _parked, closed only once `## Result` is written and no row is live,
    and unknown otherwise when the Goal can't be read. tickOn: Heartbeat is `tick` and the
    coordinator's link names this machine."""
    as_of = {"project": _mtime(folder / "project.md"), "tick": _mtime(folder / "tick.json")}
    try:
        lines = (folder / "project.md").read_text().split("\n")
        data = status_data(lines, live=False)
        try:
            threads, prs, prs_at = _seen(folder / "tick.json")
        except (OSError, ValueError):  # the project still shows, with no tick data
            (threads, prs, prs_at), as_of["tick"] = ({}, {}, {}), None
        # When the tick last read each state shown: one it kept from an earlier look, as it
        # does for a failed read or a PR while the coordinator runs, keeps that look's time.
        # A look from before the tick kept times is undated, and so is one the tick should
        # hold but doesn't, such as a live row's thread whose first read failed: either way
        # the card has no tick data.
        read, here = [], this_environment()
        for unit in (unit for group in data["groups"] for unit in group["units"]):
            link = LINK.search(unit["thread"] or "")
            seen = threads.get(link.group(2)) if link and not FINAL.match(unit["state"]) else None
            if isinstance(seen, dict) and seen.get("status"):
                unit["thread_status"] = seen["status"]
                read.append(seen.get("at"))
            elif link and THREAD_ROW.match(unit["state"]) and link.group(1) == here:
                read.append(None)
            for pr in unit["prs"]:
                state = prs.get(pr["ref"])
                if isinstance(state, list) and len(state) == 2:
                    pr["state"], pr["draft"] = state
                    read.append(prs_at.get(pr["ref"]))
                elif PR_ROW.match(unit["state"]) and pr["url"] is not None:
                    read.append(None)
        if read:
            as_of["tick"] = None if None in read else min(read)
        lead = LINK.search(_header(lines, "Coordinator"))
        ticking = ("## Listening" in lines and _listened(lines, "Heartbeat") == "tick" and lead is not None
                   and lead.group(1) == here)
        return {"folder": folder.name, "state": "ok", "data": data, "phase": _phase(lines, data), "asOf": as_of,
                "tickOn": ticking}
    except Exception as error:  # whatever a file holds, the page gets a card that says so
        return {"folder": folder.name, "state": "unknown", "error": str(error) or type(error).__name__, "asOf": as_of}


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _seen(path: Path) -> tuple[dict, dict, dict]:
    """The threads, PRs, and PR read times tick.json holds, each {} without a tick.json.
    Raises ValueError when it holds something else."""
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return {}, {}, {}
    found = [state.get(key, {}) if isinstance(state, dict) else None for key in ("threads", "prs", "prsAt")]
    if not all(isinstance(part, dict) for part in found):
        raise ValueError(f"{path} doesn't hold the tick's threads and prs")
    return found[0], found[1], found[2]


def _phase(lines: list[str], data: dict) -> str:
    """snapshot's phase. Closed needs a `## Result` with text and a Workers table it can read,
    present, whose rows are all FINAL; a Result beside a live or unread row, an empty Result, or a
    Workers table it can't read is unknown, since the project may be closing or only
    recording an interim result. A parked Goal is parked unless such a Result says otherwise."""
    if "## Goal" not in lines or data["goal"] is None:
        return "unknown"
    headings = [i for i, text in enumerate(lines) if text == "## Result" or text.startswith("## Result (")]
    if not headings:
        return "parked" if _parked(lines) else "active"
    written = all(any(text.strip() for text in lines[i + 1:_end(lines, i)]) for i in headings)
    table = [] if "## Workers" not in lines else [
        text for text in lines[slice(*_section(lines, "Workers"))] if text.startswith("|")]
    unread = len(table) < 2 or COLUMNS["state"] not in _cells(table[0]) or not re.match(r"\|\s*:?-", table[1])
    live = unread or data["unread_rows"] or any(not FINAL.match(unit["state"])
                                                for group in data["groups"] for unit in group["units"])
    if _parked(lines):
        return "unknown" if live else "parked"
    return "closed" if written and not live else "unknown"


def status_data(lines: list[str], *, live: bool = True) -> dict:
    """The project's overview as JSON-ready data, read-only. Text stays as project.md holds
    it, unescaped. Groups come in STATUS_ORDER, each Workers row a unit
    with its worker, thread link, State, PRs, Issue, and Waits on. Live fields come from
    `t3` and `gh`: a unit's `thread_status` and a resolved PR's `read`, `title`, `state`,
    `draft`, and `checks`. With live=False they're absent and neither runs; the checkout's
    origin is still read from git, since `#N` resolves against it."""
    goal = _body(lines, "Goal")
    data: dict = {"project": lines[0].removeprefix("# ◆").strip() if lines else None,
                  "goal": goal[0] if goal else None, "queue": None, "queue_unread": None,
                  "groups": [], "unread_rows": [], "decisions": _body(lines, "Decisions"),
                  "phases": _body(lines, "Phases")}
    try:
        items = project_queue.read(lines)
        data["queue"] = None if items is None else [asdict(item) for item in items]
    except project_queue.QueueError as error:
        data["queue_unread"] = str(error)
    if "## Workers" in lines:
        origin, reads = _origin(_checkout(lines)), {}
        rows, odd = _workers(lines)
        groups: dict[str, list[dict]] = {}
        for row in rows:
            match = STATE.match(row.get(COLUMNS["state"], ""))
            group = (match.group(1) or "replaced/absorbed") if match else "other"
            groups.setdefault(group, []).append(_unit(row, origin, live, reads))
        data["groups"] = [{"state": name, "units": groups[name]}
                          for name in sorted(groups, key=lambda name: STATUS_ORDER.index(name))]
        data["unread_rows"] = [(_cells(line) or ["?"])[0] for line in odd]
    return data


STATUS_PAGE = Path(__file__).with_name("status.html")
STATUS_DATA = '<script type="application/json" id="status-data">null</script>'  # draw(data)'s feed


def status_html(data: dict) -> str:
    """status.html with status_data's data baked into its status-data block, so the page
    draws it with no network. The block holds the data's UTF-8 JSON in base64, as a JSON
    string: no project.md text can end the block, even when html_render's `html` input
    turns each `\\uXXXX` back into its character, and the page sets text through textContent."""
    page = STATUS_PAGE.read_text()
    if page.count(STATUS_DATA) != 1:
        raise ValueError(f"{STATUS_PAGE} must hold the status-data block exactly once")
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    return page.replace(STATUS_DATA, STATUS_DATA.replace("null", f'"{encoded}"'))


# status's state groups, in the order the user reads them: what needs a look, then work under
# way, then work that ended; `other` holds a State a hand edit left outside STATES.
STATUS_ORDER = ["stuck", "waiting", "overdue", "unknown", "running", "queued", "done", "dropped",
                "replaced/absorbed", "other"]
EMPTY = ("", "—", "-")  # a cell that holds nothing


def _body(lines: list[str], name: str) -> list[str]:
    """The non-blank lines of `## name`, or [] when it has none or isn't there."""
    if f"## {name}" not in lines:
        return []
    start_at, end = _section(lines, name)
    return [text for text in lines[start_at + 1:end] if text.strip()]


def _unit(row: dict[str, str], origin: str, live: bool, reads: dict) -> dict:
    """One Workers row as status_data's unit. `thread_status` is there only when the thread
    was read: live, linked, on this machine's T3 or `unread`, and its row not FINAL."""
    state = row.get(COLUMNS["state"], "")
    link = LINK.search(row.get(COLUMNS["thread"], ""))
    unit: dict = {"worker": row.get("Worker", "?"), "thread": link.group(0) if link else None, "state": state}
    if live and link and not FINAL.match(state):
        here = this_environment()
        seen = show_thread(link.group(2)) if here and link.group(1) == here else None
        unit["thread_status"] = (seen.get("status") or "unread") if seen else "unread"
    refs: set[str] = set()
    _pr_refs(row.get(COLUMNS["pr"], ""), origin, refs)
    unit["prs"] = [_pr_data(ref, origin, live, reads)
                   for ref in sorted(refs, key=lambda ref: (ref.split("#")[0], int(ref.split("#")[1])))]
    issue, waits = row.get(COLUMNS["issue"], ""), row.get(COLUMNS["waits"], "")
    unit["issue"], unit["waits_on"] = (issue if issue not in EMPTY else None), (waits if waits not in EMPTY else None)
    return unit


def _pr_data(ref: str, origin: str, live: bool, reads: dict) -> dict:
    """A PR as {ref, name, url}: url None when its repo isn't known, and name `#N` in the
    checkout's repo, `owner/repo#N` in another. A live read of a resolved PR adds `read`,
    and when it read, its title, state, draft, and checks: None when they didn't read."""
    if ref.startswith("?"):
        return {"ref": ref, "name": ref.lstrip("?/"), "url": None}
    repo, number = ref.split("#")
    pr: dict = {"ref": ref, "name": f"#{number}" if repo == origin else ref,
                "url": f"https://github.com/{repo}/pull/{number}"}
    if live:
        if ref not in reads:  # a PR on several rows is read once, so every card shows the same read
            pr_read = _pr(ref)
            reads[ref] = (pr_read, None if pr_read is None else _checks(ref))
        seen, checks = reads[ref]
        pr["read"] = seen is not None
        if seen is not None:
            pr.update(title=seen["title"], state=seen["state"], draft=seen["isDraft"], checks=checks)
    return pr


def tick_message(lines: list[str], due: list[tuple[str, str]], path: Path) -> str:
    project = lines[0].removeprefix("# ◆").strip() if lines else "?"
    return "\n".join([f'<coordinator-tick project="{project}">', *(f"- {line}" for _, line in due),
                      "</coordinator-tick>",
                      f"Read {path} and handle each line with step 4 of the coordinator skill, loading it only "
                      "if it isn't in your context. Fix the line's row in project.md, or the tick repeats it hourly."])


def _write_page(name: str, text: str) -> Path:
    """Writes status's page as `<name>.html` in a temp folder only this user can open, and
    returns its path. The file is replaced whole, so a link planted at its path is never
    followed."""
    folder = Path(tempfile.gettempdir()) / f"addystack-status-{os.getuid()}"
    folder.mkdir(mode=0o700, exist_ok=True)
    seen = os.lstat(folder)
    if not stat.S_ISDIR(seen.st_mode) or seen.st_uid != os.getuid() or seen.st_mode & 0o077:
        raise ProjectError(f"{folder} isn't a folder only this user can open: remove it, then run status again")
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".status.", suffix=".html")  # mode 0600
    with os.fdopen(handle, "w") as f:
        f.write(text)
    page = folder / f"{name}.html"
    os.replace(tmp, page)
    return page


def _write(path: Path, text: str) -> None:
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=".project.md.")
    with os.fdopen(handle, "w") as f:
        f.write(text)
    os.chmod(tmp, path.stat().st_mode if path.exists() else 0o644)  # mkstemp makes it 0600
    os.replace(tmp, path)


def _tick(folder: Path, lines: list[str], send: bool) -> int:
    """Runs tick: with --send only while Listening's Heartbeat is `tick`, saving the state
    only after the message went out, so a failed send is retried next tick."""
    if send and _listened(lines, "Heartbeat") != "tick":
        return 0
    # A copy of a project whose coordinator runs on another machine: T3 here can't read or
    # message its thread, and that machine's timer ticks it.
    lead, here = LINK.search(_header(lines, "Coordinator")), this_environment()
    if lead and here and lead.group(1) != here:
        if not send:
            print(f"its coordinator's thread is on environment {lead.group(1)}, not this machine's {here}, "
                  "so that machine's timer ticks it")
        return 0
    store = folder / "tick.json"
    try:
        state = json.loads(store.read_text()) if store.exists() else {}
    except ValueError:
        state = {}
    if not send:
        stamp = folder.parent / TIMER_STAMP
        if not stamp.exists() or time.time() - stamp.stat().st_mtime > 1200:
            print("the tick timer hasn't run in 20 minutes: install it as references/tick.md says")
    result = tick(lines, state, time.time(), hold=send)
    if result is None:
        return 1
    due, after = result
    if not send:
        print("\n".join(f"- {line}" for _, line in due) or "nothing new")
        return 0
    if due:
        code, out = _run(["t3", "thread", "send", LINK.search(_header(lines, "Coordinator")).group(2), "-"],
                         stdin=tick_message(lines, due, folder / "project.md"))
        if code:
            raise ProjectError(f"t3 thread send failed: {out.strip()[:300]}")
    _write(store, json.dumps(after, indent=1) + "\n")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="project.py", description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", allow_abbrev=False)
    for name in ("project", "coordinator", "checkout", "mode", "goal", "proof"):
        init.add_argument(f"--{name}", required=True)
    for name in ("decide", "learn"):
        commands.add_parser(name).add_argument("text")
    row = commands.add_parser("worker", allow_abbrev=False)
    row.add_argument("slug")
    for name in COLUMNS:
        row.add_argument(f"--{name}")
    listening = commands.add_parser("listen")
    listening.add_argument("key")
    listening.add_argument("value")
    ending = commands.add_parser("phase", allow_abbrev=False)
    ending.add_argument("slug")
    ending.add_argument("--result", required=True)
    ending.add_argument("--proof")
    next_or_park = ending.add_mutually_exclusive_group(required=True)
    next_or_park.add_argument("--goal")
    next_or_park.add_argument("--park")
    starting = commands.add_parser("start", allow_abbrev=False)
    starting.add_argument("--goal", required=True)
    starting.add_argument("--proof", required=True)
    commands.add_parser("tick", allow_abbrev=False).add_argument("--send", action="store_true")
    showing = commands.add_parser("status", allow_abbrev=False)
    showing.add_argument("--json", action="store_true")
    showing.add_argument("--html", action="store_true")
    showing.add_argument("--no-live", action="store_true")
    queued = commands.add_parser("queue", allow_abbrev=False).add_subparsers(dest="action", required=True)
    adding = queued.add_parser("add", allow_abbrev=False)
    adding.add_argument("kind", choices=project_queue.KINDS)
    adding.add_argument("name")
    adding.add_argument("--from", dest="source")
    resolving = queued.add_parser("done", allow_abbrev=False)
    resolving.add_argument("ident", type=int, metavar="id")
    resolving.add_argument("--answer", required=True)
    queued.add_parser("show", allow_abbrev=False)
    importing = queued.add_parser("import", allow_abbrev=False)
    importing.add_argument("--from", dest="sources", action="append", metavar="ID=WHO")
    importing.add_argument("--stuck", type=int, action="append", metavar="ID")
    args = parser.parse_args(argv)
    if args.command == "status" and not (args.json or args.html):
        showing.error("status takes --json, --html, or both")
    if args.command == "phase" and (args.goal is None) != (args.proof is None):
        ending.error("--goal needs --proof, and --park takes neither")
    path = args.dir / "project.md"
    try:
        if args.command == "init":
            if path.exists():
                raise ProjectError(f"{path} exists")
            args.dir.mkdir(parents=True, exist_ok=True)
            _write(path, SKELETON.format(**{k: v for k, v in vars(args).items() if k not in ("dir", "command")}))
            print(path)
            return 0
        if not path.is_file():
            raise ProjectError(f"no {path}: run init first")
        if args.command == "phase":
            snapshot = path.read_bytes()
            lines = snapshot.decode().replace("\r\n", "\n").replace("\r", "\n").split("\n")  # as read_text does
            if not SLUG.match(args.slug):
                raise ProjectError(f"slug {args.slug!r} isn't lowercase words joined by hyphens")
            ends = {"goal": args.goal, "proof": args.proof, "park": args.park}
            phase(lines[:], f"phases/00-{args.slug}.md", args.result, **ends)  # every refusal, before any write
            archive = _archive(args.dir, snapshot, args.slug)
            phase(lines, archive, args.result, **ends)
            _write(path, "\n".join(lines))
            if unread := _drop_final(lines):  # phase dropped the rest, so this only names them
                print(f"kept {len(unread)} Workers rows whose cells don't match the header, so their"
                      f" State is unread: {', '.join(unread)}. Fix or delete each by hand.", file=sys.stderr)
            print(args.dir / archive)
            print(path)
            return 0
        lines = path.read_text().split("\n")
        if args.command == "tick":
            return _tick(args.dir, lines, args.send)
        if args.command == "status":
            data = status_data(lines, live=not args.no_live)
            if args.html:
                page = _write_page(args.dir.resolve().name, status_html(data))
            if args.json:
                print(json.dumps({**data, "html_path": str(page)} if args.html else data, ensure_ascii=False, indent=2))
            else:
                print(page)
            return 0
        if args.command == "queue":
            answer = getattr(args, "answer", None)
            printed = queue(lines, args.action, kind=getattr(args, "kind", None), name=getattr(args, "name", None),
                            source=getattr(args, "source", None), ident=getattr(args, "ident", None),
                            answer=sys.stdin.read() if answer == "-" else answer,
                            block=sys.stdin.read() if args.action == "import" else None,
                            sources=getattr(args, "sources", None), stuck=getattr(args, "stuck", None))
            if args.action != "show":
                _write(path, "\n".join(lines))
            print(printed)
            return 0
        if args.command in ("decide", "learn"):
            body = sys.stdin.read() if args.text == "-" else args.text
            (decide if args.command == "decide" else learn)(lines, body)
        elif args.command == "start":
            start(lines, args.goal, args.proof)
        elif args.command == "worker":
            worker(lines, args.slug, **{key: getattr(args, key) for key in COLUMNS})
        else:
            listen(lines, args.key, sys.stdin.read() if args.value == "-" else args.value)
        _write(path, "\n".join(lines))
    except ProjectError as error:
        print(error, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

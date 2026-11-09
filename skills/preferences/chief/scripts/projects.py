#!/usr/bin/env python3
"""Prints one machine's coordinator projects as compact JSON, for chief's card: each
`~/.local/state/orchestrate/<project>/project.md` (coordinator/references/project.md)
reduced to its name, coordinator link, goal line, and the Workers rows not yet done.

The Mac has no sshd, and T3 has no tool that reads a file on a linked machine, so
chief sends the Mac feed thread a message each run (references/setup.md). The feed runs
this as `git show <ref>:chief/scripts/projects.py | python3 -` and replies with its
output, which chief reads with t3_thread_read. So it stays one stdlib file, imports
nothing beside it, and runs on Python 3.9.

  projects.py [--root DIR]     DIR defaults to ~/.local/state/orchestrate
"""
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = "~/.local/state/orchestrate"
LINK = re.compile(r"<?(t3-thread://v[12]/[^>\s·]+)>?")
CELL = re.compile(r"(?<!\\)\|")
# A Workers row's State cell opens with one of project.py's STATES.
DONE = re.compile(r"\s*(done|dropped|replaced by|absorbed into)\b", re.I)
GOAL_CHARS = 160
CELL_CHARS = 120


def cut(text, longest):
    text = " ".join(text.split())
    return text if len(text) <= longest else text[:longest - 1].rstrip() + "…"


def sections(text):
    """`## Name` → its lines, and the title line."""
    found, name, title = {}, None, ""
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            name = line[3:].strip()
            found[name] = []
        elif name:
            found[name].append(line)
    return title, found


def cells(row):
    parts = [part.strip() for part in CELL.split(row.strip())]
    return parts[1:-1] if len(parts) > 2 else parts


def workers(lines):
    """The Workers table's rows that aren't done, as dicts keyed by the header's names."""
    rows = [line for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    header = [name.lower() for name in cells(rows[0])]
    found = []
    for row in rows[2:]:
        values = dict(zip(header, cells(row)))
        state = values.get("state", "")
        if DONE.match(state):
            continue
        thread = LINK.search(values.get("thread", ""))
        found.append({
            "worker": cut(values.get("worker", ""), 60),
            "thread": thread.group(1) if thread else None,
            "state": cut(state, CELL_CHARS),
            "waits": cut(values.get("waits on", ""), CELL_CHARS),
        })
    return found


def digest(path):
    text = path.read_text(errors="replace")
    title, found = sections(text)
    head = text.split("\n## ", 1)[0]
    coordinator = LINK.search(head[head.find("Coordinator:"):] if "Coordinator:" in head else "")
    goal = next((line for line in found.get("Goal", []) if line.strip()), "")
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return {
        "project": title.lstrip("◆ ").strip() or path.parent.name,
        "coordinator": coordinator.group(1) if coordinator else None,
        "goal": cut(goal, GOAL_CHARS),
        "workers": workers(found.get("Workers", [])),
        "modified": modified.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def read_all(root):
    projects = []
    for path in sorted(Path(root).expanduser().glob("*/project.md")):
        try:
            projects.append(digest(path))
        except (OSError, UnicodeError):
            continue
    return projects


def main(argv):
    parser = argparse.ArgumentParser(prog="projects.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=ROOT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps({"read": now, "projects": read_all(args.root)}, ensure_ascii=False,
                     separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

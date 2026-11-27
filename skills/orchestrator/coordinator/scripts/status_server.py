#!/usr/bin/env python3
"""Serves the live status page for every coordinator project on this machine, bound to
127.0.0.1 (references/status-page.md). `addystack install` runs it under launchd while
`coordinator.statusPage` is on.

  status_server.py --port N [--root DIR]

  GET /               status.html with no data baked in, so it runs in live mode
  GET /overview.json  200 Page with an ETag, or 304 when If-None-Match equals it
  anything else       404; a Host that isn't localhost:N or 127.0.0.1:N gets 403

Every reply carries `Server: addystack-coordinator-status`, which doctor checks, and no
CORS header. It writes nothing: each project's card is project.snapshot's.

    Page = {machine: str, staleAfter: int, timer: float | None, projects: [Card, ...]}

Projects come unknown and active first, then parked, then closed; more queue items first.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path("~/.local/state/orchestrate").expanduser()
SERVER = "addystack-coordinator-status"

# (folder name, project.md mtime_ns, tick.json mtime_ns or 0), one per folder holding a
# project.md, then the timer's .tick stamp.
Signature = tuple


def signature(root: Path) -> Signature:
    """Every project folder's file change times, by stat calls alone."""
    raise NotImplementedError


def tag(seen: Signature) -> str:
    """The ETag for a signature."""
    raise NotImplementedError


def collect(root: Path) -> dict:
    """The Page: project.snapshot for each folder holding a project.md, in page order."""
    raise NotImplementedError


def serve(port: int, root: Path = ROOT) -> None:
    """Binds 127.0.0.1:port and blocks. Keeps the last (tag, body), so an unchanged poll
    costs stat calls and no parse."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))

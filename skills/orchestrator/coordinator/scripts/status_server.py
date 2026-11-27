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

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import project

ROOT = Path("~/.local/state/orchestrate").expanduser()
SERVER = "addystack-coordinator-status"
PAGE = Path(__file__).resolve().parent / "status.html"
# Each server start tags its pages apart from the last one's, so a page polling across an
# update that changed the server fetches the new body instead of keeping the old one.
_STARTED = os.urandom(8).hex()
_ORDER = {"unknown": 0, "active": 0, "parked": 1, "closed": 2}

# (folder name, project.md mtime_ns, tick.json mtime_ns or 0), one per folder holding a
# project.md, then the timer's .tick stamp.
Signature = tuple


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def signature(root: Path) -> Signature:
    """Every project folder's file change times, by stat calls alone."""
    try:
        names = sorted(entry.name for entry in os.scandir(root) if entry.is_dir())
    except OSError:
        names = []
    found = [(name, changed, _mtime_ns(root / name / "tick.json") or 0) for name in names
             for changed in [_mtime_ns(root / name / "project.md")] if changed is not None]
    return (*found, _mtime_ns(root / project.TIMER_STAMP) or 0)


def tag(seen: Signature) -> str:
    """The ETag for a signature."""
    return '"' + hashlib.sha256(repr((_STARTED, seen)).encode()).hexdigest()[:32] + '"'


def _rank(card: dict) -> tuple:
    queue = card.get("data", {}).get("queue") or []
    return _ORDER[card.get("phase", "unknown")], -len(queue), card["folder"]


def collect(root: Path) -> dict:
    """The Page: project.snapshot for each folder holding a project.md, in page order."""
    cards = [project.snapshot(root / name) for name, *_ in signature(root)[:-1]]
    stamp = root / project.TIMER_STAMP
    return {"machine": socket.gethostname(), "staleAfter": project.STALE,
            "timer": stamp.stat().st_mtime if stamp.exists() else None, "projects": sorted(cards, key=_rank)}


def _json(page: dict) -> bytes:
    """page as JSON a <script> can hold: `<`, `>`, and `&` only occur inside its strings,
    where their escapes mean the same, so text such as `</script>` stays text."""
    text = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").encode()


class _Server(ThreadingHTTPServer):
    """The bound server, holding what every request shares: the root, the Host values it
    answers, and the last (tag, body) it served."""

    def __init__(self, port: int, root: Path) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.root = root
        self.hosts = {f"{host}:{self.server_address[1]}" for host in ("localhost", "127.0.0.1")}
        self.last, self.lock = ("", b""), threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def version_string(self) -> str:
        return SERVER

    def log_request(self, code="-", size="-") -> None:
        pass  # a poll every 2 s would fill launchd's log; errors still go there

    def do_GET(self) -> None:
        if (self.headers.get("Host") or "").lower() not in self.server.hosts:
            return self._reply(403, b"this page answers only at localhost\n", "text/plain")
        path = urlsplit(self.path).path
        if path == "/overview.json":
            return self._overview()
        if path != "/":
            return self._reply(404, b"not found\n", "text/plain")
        try:
            body = PAGE.read_bytes()
        except OSError:
            return self._reply(503, b"status.html isn't installed beside status_server.py yet; "
                                    b"/overview.json has the data\n", "text/plain")
        self._reply(200, body, "text/html")

    def _overview(self) -> None:
        server = self.server
        etag = tag(signature(server.root))
        with server.lock:
            if server.last[0] != etag:
                server.last = (etag, _json(collect(server.root)))
            body = server.last[1]
        asked = {value.strip().removeprefix("W/") for value in (self.headers.get("If-None-Match") or "").split(",")}
        if etag in asked or "*" in asked:
            return self._reply(304, b"", None, etag)
        self._reply(200, body, "application/json", etag)

    def _reply(self, code: int, body: bytes, kind: str | None, etag: str | None = None) -> None:
        self.send_response(code)
        if kind:
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        if code != 304:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


def serve(port: int, root: Path = ROOT) -> None:
    """Binds 127.0.0.1:port and blocks. Keeps the last (tag, body), so an unchanged poll
    costs stat calls and no parse."""
    with _Server(port, root) as server:
        server.serve_forever()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="status_server.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help="the orchestrate folder, ~/.local/state/orchestrate")
    args = parser.parse_args(argv)
    try:
        serve(args.port, args.root)
    except OSError as error:
        print(f"status_server.py: can't serve 127.0.0.1:{args.port}: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

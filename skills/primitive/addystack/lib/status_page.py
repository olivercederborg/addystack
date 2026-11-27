"""The coordinator status page's machine setup on macOS: the `coordinator.statusPage`
setting, its fixed port, its launchd agent, and its health.

The coordinator skill owns the page and its server (coordinator/scripts/status_server.py).
This module owns only the switch: while the setting is on, install writes the agent's
plist and starts it, and from then on reconcile's ledger records it as install's (key
`statusPage`). Once it's off, install stops an agent the ledger records and removes its
plist. The plist holds a SHA-256 of the server's sources, so an update restarts it.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import plistlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import hookset
import launchd
import skills_cli
from config import Resolved

AGENT = launchd.Agent("addystack.coordinator-status", "the coordinator status page")
PORT = int(os.environ.get("ADDYSTACK_STATUS_PORT", "47130"))  # the override is for tests
SERVER = Path("coordinator") / "scripts" / "status_server.py"  # in a host's skill folder
HEADER = "addystack-coordinator-status"  # the Server header status_server.py sends
LOG = Path("Library") / "Logs" / "addystack-coordinator-status.err.log"  # under home


def url() -> str:
    """http://localhost:<PORT>/"""
    return f"http://localhost:{PORT}/"


def wanted(resolved: Resolved) -> bool:
    """coordinator.statusPage, on the darwin host profile."""
    return resolved["coordinator"]["statusPage"] is True and hookset.host_profile() == "darwin"


def _server(resolved: Resolved) -> Optional[Path]:
    """status_server.py in the first enabled host's skill folder that holds it, by the
    path through that folder, so a moved checkout or a reinstall behind its link still runs."""
    for host in ("claude", "codex"):
        path = skills_cli.folder(host) / SERVER
        if resolved["hosts"].get(host) and path.is_file():
            return path
    return None


def _digest(scripts: Path) -> str:
    """A SHA-256 of every Python source the server runs: the scripts folder's .py files
    but its tests."""
    digest = hashlib.sha256()
    for path in sorted(scripts.glob("*.py")):
        if not path.name.startswith("test_"):
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def plist_text(resolved: Resolved) -> Optional[str]:
    """The agent's plist, or None when it isn't wanted or no host's skill folder holds
    coordinator/scripts/status_server.py. Runs that server with --port PORT, KeepAlive."""
    server = _server(resolved) if wanted(resolved) else None
    if server is None:
        return None
    return plistlib.dumps({
        "Label": AGENT.label,
        "ProgramArguments": ["/usr/bin/python3", str(server), "--port", str(PORT)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {"ADDYSTACK_STATUS_SHA256": _digest(server.parent)},
        "StandardErrorPath": str(Path.home() / LOG),
    }).decode()


def plan(resolved: Resolved, writes: Dict[Path, str], owned: bool
         ) -> Tuple[List[Tuple[str, Path, str, bool]], bool]:
    """guard.plan's shape, each change of kind `status-page`: launchd.plan for AGENT with
    plist_text(resolved)."""
    changes, owned = launchd.plan(AGENT, plist_text(resolved), owned, writes)
    why = (f"no enabled host's skill folder has {SERVER}" if wanted(resolved)
           else "coordinator.statusPage is off on this machine")
    return [("status-page", path, detail if start else f"{detail}: {why}", start)
            for path, detail, start in changes], owned


def _answer() -> Optional[str]:
    """The Server header of what answers GET url(), "" for a reply without one, or None
    when nothing answers within two seconds."""
    connection = http.client.HTTPConnection("localhost", PORT, timeout=2)
    try:
        connection.request("GET", "/")
        return connection.getresponse().getheader("Server") or ""
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def problems(resolved: Resolved) -> List[str]:
    """What doctor reports while it's wanted: launchd.problems for AGENT, plus nothing
    answering at url(), or a server there without the `Server: addystack-coordinator-status`
    header. None when it isn't wanted."""
    if not wanted(resolved):
        return []
    text = plist_text(resolved)
    if text is None:
        return [f"no enabled host's skill folder has {SERVER}"]
    lines = launchd.problems(AGENT, text)
    if lines:
        return lines
    answer = _answer()
    if answer is None:
        return [f"nothing answers at {url()}; see {Path.home() / LOG}"]
    if answer != HEADER:
        return [f"{url()} answers, but not as the status page (Server: {answer or 'none'}); another program has "
                f"port {PORT}"]
    return []

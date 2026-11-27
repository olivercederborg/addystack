"""The coordinator status page's machine setup on macOS: the `coordinator.statusPage`
setting, its fixed port, its launchd agent, and its health.

The coordinator skill owns the page and its server (coordinator/scripts/status_server.py).
This module owns only the switch: while the setting is on, install writes the agent's
plist and starts it, and from then on reconcile's ledger records it as install's (key
`statusPage`). Once it's off, install stops an agent the ledger records and removes its
plist. The plist holds a SHA-256 of the server's sources, so an update restarts it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import launchd
from config import Resolved

AGENT = launchd.Agent("addystack.coordinator-status", "the coordinator status page")
PORT = int(os.environ.get("ADDYSTACK_STATUS_PORT", "47130"))  # the override is for tests


def url() -> str:
    """http://localhost:<PORT>/"""
    raise NotImplementedError


def wanted(resolved: Resolved) -> bool:
    """coordinator.statusPage, on the darwin host profile."""
    raise NotImplementedError


def plist_text(resolved: Resolved) -> Optional[str]:
    """The agent's plist, or None when it isn't wanted or no host's skill folder holds
    coordinator/scripts/status_server.py. Runs that server with --port PORT, KeepAlive."""
    raise NotImplementedError


def plan(resolved: Resolved, writes: Dict[Path, str], owned: bool
         ) -> Tuple[List[Tuple[str, Path, str, bool]], bool]:
    """guard.plan's shape, each change of kind `status-page`: launchd.plan for AGENT with
    plist_text(resolved)."""
    raise NotImplementedError


def problems(resolved: Resolved) -> List[str]:
    """What doctor reports while it's wanted: launchd.problems for AGENT, plus nothing
    answering at url(), or a server there without the `Server: addystack-coordinator-status`
    header. None when it isn't wanted."""
    raise NotImplementedError

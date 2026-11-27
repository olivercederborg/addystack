"""One labelled launchd agent that `addystack install` owns: its plist's path, whether launchd
has it loaded, and starting and stopping it. guard.py's agent and status_page.py's agent
both use it, so launchctl handling lives in one place.

`ADDYSTACK_LAUNCHCTL` overrides the launchctl it runs, so tests use a stub by absolute
path and a broken stub can never fall through to the real one on PATH.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Agent:
    label: str  # "addystack.coordinator-status"
    name: str   # "the coordinator status page", for install's change lines and doctor's

    def plist(self) -> Path:
        """~/Library/LaunchAgents/<label>.plist."""
        raise NotImplementedError

    def loaded(self) -> Optional[bool]:
        """Whether launchd has the agent, or None when launchctl couldn't say: only its
        no-such-service status counts as absent, so a failed query never passes for a stop."""
        raise NotImplementedError

    def start(self) -> None:
        """(Re)loads the agent from its plist. When launchd won't load it, the plist goes
        too, so the next install writes it and tries again. Raises OSError then."""
        raise NotImplementedError

    def unload(self) -> None:
        """Stops the agent. Raises OSError while launchd still has it, or can't say."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stops the agent and removes its plist. Raises OSError while launchd still has it."""
        raise NotImplementedError


def plan(agent: Agent, text: Optional[str], owned: bool, writes: Dict[Path, str]
         ) -> Tuple[List[Tuple[Path, str, bool]], bool]:
    """Each change as (plist, detail, start), and whether the ledger records the agent as
    install's once they're made. text None means the agent isn't wanted: one the ledger
    owns stops (start False), and one set up by hand stays. A changed text is added to
    writes and starts. Raises ValueError when launchctl can't say whether it's loaded."""
    raise NotImplementedError


def problems(agent: Agent, text: str) -> List[str]:
    """What doctor reports for a wanted agent: its plist missing, differing from text, or
    not loaded. None when all hold."""
    raise NotImplementedError

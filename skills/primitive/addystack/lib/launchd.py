"""One labelled launchd agent that `addystack install` owns: its plist's path, whether launchd
has it loaded, and starting and stopping it. guard.py's agent and status_page.py's agent
both use it, so launchctl handling lives in one place.

`ADDYSTACK_LAUNCHCTL` overrides the launchctl it runs, so tests use a stub by absolute
path and a broken stub can never fall through to the real one on PATH.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# launchctl print's exit status for a service launchd doesn't have.
_NO_SERVICE = 113


def _launchctl(*args: str) -> Optional[int]:
    """launchctl's exit status, or None when it couldn't run."""
    try:
        return subprocess.run([os.environ.get("ADDYSTACK_LAUNCHCTL", "launchctl"), *args], capture_output=True, timeout=10,
                              stdin=subprocess.DEVNULL).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _read(path: Path) -> Optional[str]:
    """The file's text, or None when it doesn't exist. Raises ValueError when it exists but
    can't be read, so install never replaces a file it couldn't see."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"can't read {path}: {error}") from error


@dataclass(frozen=True)
class Agent:
    label: str  # "addystack.coordinator-status"
    name: str   # "the coordinator status page", for install's change lines and doctor's

    def plist(self) -> Path:
        """~/Library/LaunchAgents/<label>.plist."""
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"

    def loaded(self) -> Optional[bool]:
        """Whether launchd has the agent, or None when launchctl couldn't say: only its
        no-such-service status counts as absent, so a failed query never passes for a stop."""
        status = _launchctl("print", f"{_domain()}/{self.label}")
        return True if status == 0 else False if status == _NO_SERVICE else None

    def start(self) -> None:
        """(Re)loads the agent from its plist. When launchd won't load it, the plist goes
        too, so the next install writes it and tries again. Raises OSError then."""
        path = self.plist()
        _launchctl("bootout", f"{_domain()}/{self.label}")
        if _launchctl("bootstrap", _domain(), str(path)) != 0:
            os.unlink(path)
            raise OSError(f"launchctl couldn't load {path}; run addystack install again")

    def unload(self) -> None:
        """Stops the agent. Raises OSError while launchd still has it, or can't say."""
        _launchctl("bootout", f"{_domain()}/{self.label}")
        if self.loaded() is not False:
            raise OSError(f"launchctl couldn't stop {self.label}, or couldn't say; run addystack install again")

    def stop(self) -> None:
        """Stops the agent and removes its plist. Raises OSError while launchd still has it."""
        self.unload()
        try:
            os.unlink(self.plist())
        except FileNotFoundError:
            pass


def plan(agent: Agent, text: Optional[str], owned: bool, writes: Dict[Path, str]
         ) -> Tuple[List[Tuple[Path, str, bool]], bool]:
    """Each change as (plist, detail, start), and whether the ledger records the agent as
    install's once they're made. text None means the agent isn't wanted: one the ledger
    owns stops (start False), and one set up by hand stays. A changed text is added to
    writes and starts. Raises ValueError when launchctl can't say whether it's loaded."""
    path = agent.plist()
    if text is None:
        return ([(path, f"stops {agent.name} and removes its plist", False)] if owned else []), False
    current = _read(path)
    if current != text:
        writes[path] = text
        verb = "writes" if current is None else "updates"
        return [(path, f"{verb} {agent.name}'s launchd plist and starts it", True)], True
    state = agent.loaded()
    if state is None:
        raise ValueError(f"launchctl couldn't say whether {agent.label} is loaded; run addystack install again")
    return ([(path, f"starts {agent.name}, which isn't loaded", True)] if state is False else []), True


def problems(agent: Agent, text: str) -> List[str]:
    """What doctor reports for a wanted agent: its plist missing, differing from text, or
    not loaded. None when all hold."""
    current = _read(agent.plist())
    if current is None:
        return [f"{agent.plist()} is missing"]
    if current != text:
        return [f"{agent.plist()} differs from the kit's"]
    state = agent.loaded()
    if state is None:
        return [f"launchctl couldn't say whether {agent.name} is loaded"]
    return [f"{agent.name} isn't loaded"] if state is False else []

"""The agent memory guard's machine setup on macOS: its launchd agent and the agent-shell
process limit (hooks/README.md, Agent memory guard).

Both follow the `agent-memory-guard-notice` hook's selection (hookset.guard_wanted): the
`machine` tag, the darwin host profile, and `hooks.enable` and `hooks.disable` by that id.
While it's selected, install writes the launchd plist from hooks/agent-memory-guard.plist
with the kit's absolute path, (re)starts the agent when the plist changed or it isn't
loaded, and appends the process limit to ~/.zshenv unless a `ulimit -Su` line is already
there. Once it's deselected, install stops the agent and removes its plist; the ~/.zshenv
line is the user's file's, so it stays. launchctl runs by name, so tests stub it on PATH.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import hookset
from config import Resolved

LABEL = "addystack.agent-memory-guard"
TEMPLATE = Path(__file__).resolve().parent.parent / "hooks" / "agent-memory-guard.plist"
# Fork fails past 3,000 user processes in agent shells; GUI apps keep macOS's 8,000. T3
# names a Codex session's thread but sets no CLI path.
LIMIT = ("# addystack: agent shells stop forking past 3,000 user processes, the backstop for fork storms.\n"
         "[[ -n $CLAUDECODE || -n $T3CODE_CLI_PATH || -n $T3CODE_THREAD_ID ]] && ulimit -Su 3000\n")
_HAS_LIMIT = re.compile(r"^[^#\n]*\bulimit\s+-Su\b", re.M)


def plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def zshenv() -> Path:
    return Path.home() / ".zshenv"


def plist_text(resolved: Resolved) -> str:
    """The template with {{kit}} and {{home}} filled through plistlib, so a path holding &
    or < stays valid XML."""
    kit, home = os.path.expanduser(str(resolved["kit"])), str(Path.home())

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value.replace("{{kit}}", kit).replace("{{home}}", home) if isinstance(value, str) else value

    return plistlib.dumps(fill(plistlib.loads(TEMPLATE.read_bytes()))).decode()


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text()
    except OSError:
        return None


def _launchctl(*args: str) -> bool:
    try:
        return subprocess.run(["launchctl", *args], capture_output=True, timeout=10,
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _domain() -> str:
    return f"gui/{os.getuid()}"


def loaded() -> bool:
    return _launchctl("print", f"{_domain()}/{LABEL}")


def plan(resolved: Resolved, writes: Dict[Path, str]) -> List[Tuple[str, Path, str, bool]]:
    """Each change as (kind, target, detail, start): kind `guard` starts the agent when
    start is True and stops it and removes its plist when False; `shell-limit` is a write
    only. Adds each file to write to writes."""
    changes: List[Tuple[str, Path, str, bool]] = []
    path = plist()
    if not hookset.guard_wanted(resolved):
        if os.path.lexists(path):
            changes.append(("guard", path, "stops the agent memory guard and removes its plist: its hook isn't "
                            "selected", False))
        return changes
    text = plist_text(resolved)
    current = _read(path)
    if current != text:
        writes[path] = text
        changes.append(("guard", path, ("writes" if current is None else "updates")
                        + " the agent memory guard's launchd plist and starts it", True))
    elif not loaded():
        changes.append(("guard", path, "starts the agent memory guard, which isn't loaded", True))
    env = _read(zshenv())
    if env is None or not _HAS_LIMIT.search(env):
        writes[zshenv()] = (env or "") + ("\n" if env and not env.endswith("\n") else "") + LIMIT
        changes.append(("shell-limit", zshenv(), "caps agent shells at 3,000 user processes", False))
    return changes


def start(path: Path) -> None:
    """(Re)loads the agent from path, so a changed plist takes effect."""
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if not _launchctl("bootstrap", _domain(), str(path)):
        raise OSError(f"launchctl couldn't load {path}")


def stop(path: Path) -> None:
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    os.unlink(path)


def problems(resolved: Resolved) -> List[str]:
    """What doctor reports: one line per missing or stale piece, none when it's not wanted."""
    if not hookset.guard_wanted(resolved):
        return []
    lines = []
    current = _read(plist())
    if current is None:
        lines.append(f"{plist()} is missing")
    elif current != plist_text(resolved):
        lines.append(f"{plist()} differs from the kit's")
    elif not loaded():
        lines.append("the agent memory guard isn't loaded")
    env = _read(zshenv())
    if env is None or not _HAS_LIMIT.search(env):
        lines.append(f"{zshenv()} sets no agent-shell process limit")
    return lines

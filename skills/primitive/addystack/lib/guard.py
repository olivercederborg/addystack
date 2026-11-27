"""The agent memory guard's machine setup on macOS: its launchd agent and the agent-shell
process limit (hooks/README.md, Agent memory guard).

Both follow the `agent-memory-guard-notice` hook's selection (hookset.guard_wanted): the
`machine` tag, the darwin host profile, and `hooks.enable` and `hooks.disable` by that id.

- **Agent**: while it's selected, install writes the launchd plist from
  hooks/agent-memory-guard.plist with the kit's absolute path, and (re)starts the agent
  when the plist changed or it isn't loaded; from then on reconcile's ledger records the
  guard as install's. Once it's deselected, install stops a guard the ledger records,
  whether or not its plist is still there, and removes the plist; a guard the user set up
  by hand, which the ledger doesn't record, stays. A stop or start launchd refuses, or
  can't confirm, fails the install, and the next install tries again: the ledger keeps a
  guard it couldn't stop, and a plist launchd wouldn't load is removed.
- **Limit**: whether a new agent shell gets one is probed, not read: a login zsh runs once with
  each agent variable alone set and the soft limit raised to the hard one, so an early `return`, an
  `alias`, `nounset`, or a `ZDOTDIR` elsewhere all count as they would in a real shell.
  Without a limit of LIMIT or less, install appends LIMIT_LINES to the .zshenv zsh reads
  (`$ZDOTDIR`, else home), once, and doctor reports a limit that still doesn't apply. A
  .zshenv that exists but can't be read stops the install before anything is written.

`ADDYSTACK_LAUNCHCTL` overrides the launchctl it runs, so tests use a stub by absolute
path and a broken stub can never fall through to the real one on PATH.
"""
from __future__ import annotations

import os
import plistlib
import resource
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import hookset
from config import Resolved

LABEL = "addystack.agent-memory-guard"
TEMPLATE = Path(__file__).resolve().parent.parent / "hooks" / "agent-memory-guard.plist"
LIMIT = 3000
# Fork fails past LIMIT user processes in agent shells; GUI apps keep macOS's 8,000. T3
# names a Codex session's thread but sets no CLI path. `${X-}` keeps it working under
# `setopt nounset`.
# It only ever lowers a limit, so a shell already capped lower keeps its own.
LIMIT_LINES = (
    "# addystack: agent shells stop forking past 3,000 user processes, the backstop for fork storms.\n"
    "[[ -n ${CLAUDECODE-} || -n ${T3CODE_CLI_PATH-} || -n ${T3CODE_THREAD_ID-} || -n ${CODEX_THREAD_ID-} ]] &&\n"
    "  [[ $(ulimit -Su) == unlimited || $(ulimit -Su) -gt 3000 ]] && ulimit -Su 3000\n")


def plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def zshenv() -> Path:
    """The .zshenv a new zsh reads."""
    return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshenv"


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
    """The file's text, or None when it doesn't exist. Raises ValueError when it exists but
    can't be read, so install never replaces a file it couldn't see."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"can't read {path}: {error}") from error


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


def loaded() -> Optional[bool]:
    """Whether launchd has the guard, or None when launchctl couldn't say: only its
    no-such-service status counts as absent, so a failed query never passes for a stop."""
    status = _launchctl("print", f"{_domain()}/{LABEL}")
    return True if status == 0 else False if status == _NO_SERVICE else None


def _uncapped() -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    resource.setrlimit(resource.RLIMIT_NPROC, (hard, hard))


# What marks a shell as an agent's: Claude Code's, T3's for Claude, T3's for Codex, and
# Codex's own, however it was started.
AGENT_VARIABLES = ("CLAUDECODE", "T3CODE_CLI_PATH", "T3CODE_THREAD_ID", "CODEX_THREAD_ID")


def shell_limit() -> Optional[int]:
    """The highest soft process limit a new agent shell ends up with, probing a shell
    marked by each of AGENT_VARIABLES alone, or None when one has none, or zsh can't say."""
    limits = []
    for variable in AGENT_VARIABLES:
        env = {key: value for key, value in os.environ.items() if key not in AGENT_VARIABLES}
        env[variable] = "1"
        try:
            # -l, as Codex runs commands, so a .zprofile that raises the limit again counts.
            done = subprocess.run(["zsh", "-lc", "ulimit -Su"], capture_output=True, text=True, timeout=10,
                                  env=env, stdin=subprocess.DEVNULL, preexec_fn=_uncapped)
        except (OSError, subprocess.SubprocessError):
            return None
        # The last line is the probe's: .zshenv may print first.
        value = (done.stdout.strip().splitlines() or [""])[-1].strip()
        if done.returncode != 0 or not value.isdigit():
            return None
        limits.append(int(value))
    return max(limits)


def plan(resolved: Resolved, writes: Dict[Path, str], owned: bool) -> Tuple[List[Tuple[str, Path, str, bool]], bool]:
    """Each change as (kind, target, detail, start), and whether the ledger records the
    guard as install's once they're made; reconcile runs a stop before writing the ledger. Kind `guard` starts the agent from its plist when start
    is True, and stops it and removes the plist when False; `shell-limit` is a write only.
    Adds each file to write to writes. Raises ValueError as _read does."""
    path = plist()
    if not hookset.guard_wanted(resolved):
        if owned:
            return [("guard", path, "stops the agent memory guard and removes its plist: its hook isn't selected",
                     False)], False
        return [], False
    changes: List[Tuple[str, Path, str, bool]] = []
    text = plist_text(resolved)
    current = _read(path)
    if current != text:
        writes[path] = text
        changes.append(("guard", path, ("writes" if current is None else "updates")
                        + " the agent memory guard's launchd plist and starts it", True))
    elif not loaded():
        changes.append(("guard", path, "starts the agent memory guard, which isn't loaded", True))
    limit = shell_limit()
    if limit is None or limit > LIMIT:
        env = _read(zshenv())
        if env is None or LIMIT_LINES not in env:
            writes[zshenv()] = (env or "") + ("\n" if env and not env.endswith("\n") else "") + LIMIT_LINES
            changes.append(("shell-limit", zshenv(), f"caps agent shells at {LIMIT:,} user processes", False))
    return changes, True


def start(path: Path) -> None:
    """(Re)loads the agent from path, so a changed plist takes effect. When launchd won't
    load it, the plist goes too, so the next install writes it and tries again instead of
    trusting whatever guard is still running."""
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if _launchctl("bootstrap", _domain(), str(path)) != 0:
        os.unlink(path)
        raise OSError(f"launchctl couldn't load {path}; run addystack install again")


def stop(path: Path) -> None:
    """Stops the agent and removes its plist. Raises OSError while launchd still has it."""
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if loaded() is not False:
        raise OSError(f"launchctl couldn't stop {LABEL}, or couldn't say; run addystack install again")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def problems(resolved: Resolved, limit: Optional[int]) -> List[str]:
    """What doctor reports, given shell_limit()'s probe: one line per missing, stale, or
    ineffective piece; none when it's not wanted."""
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
    if limit is None or limit > LIMIT:
        got = "none" if limit is None else f"{limit:,}"
        lines.append(f"a new agent shell gets no process limit of {LIMIT:,} or less (it gets {got}); "
                     f"check {zshenv()}")
    return lines

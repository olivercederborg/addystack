"""The agent memory guard's machine setup on macOS: its launchd agent and the agent-shell
process limit (hooks/README.md, Agent memory guard).

Both follow the `agent-memory-guard-notice` hook's selection (hookset.guard_wanted): the
`machine` tag, the darwin host profile, and `hooks.enable` and `hooks.disable` by that id.

- **Agent**: while it's selected, install writes the launchd plist from
  hooks/agent-memory-guard.plist with the kit's absolute path and the guard script's
  SHA-256, since the guard reads its script once and loops, and (re)starts the agent
  when the plist changed or it isn't loaded; from then on reconcile's ledger records the
  guard as install's. Once it's deselected, install stops a guard the ledger records,
  whether or not its plist is still there, and removes the plist; a guard the user set up
  by hand, which the ledger doesn't record, stays. A stop or start launchd refuses, or
  can't confirm, fails the install, and the next install tries again: the ledger keeps a
  guard it couldn't stop, and a plist launchd wouldn't load is removed. A guard whose
  plist changes is stopped before the plist is replaced, so an install cut off before the
  restart leaves none loaded rather than the old one running.
- **Limit**: whether a new agent shell gets one is probed, not read: a login zsh runs once with
  each agent variable alone set and the soft limit raised to the hard one, so an early `return`, an
  `alias`, `nounset`, or a `ZDOTDIR` elsewhere all count as they would in a real shell.
  Without a limit of LIMIT or less, install appends LIMIT_LINES to the .zshenv zsh reads
  (`$ZDOTDIR`, else home), once, and doctor reports a limit that still doesn't apply. A
  .zshenv that exists but can't be read stops the install before anything is written.

Its launchd agent is a launchd.Agent, which runs launchctl.
"""
from __future__ import annotations

import hashlib
import os
import plistlib
import resource
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import hookset
import launchd
from config import Resolved

LABEL = "addystack.agent-memory-guard"
AGENT = launchd.Agent(LABEL, "the agent memory guard")
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
    return AGENT.plist()


def zshenv() -> Path:
    """The .zshenv a new zsh reads."""
    return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshenv"


def plist_text(resolved: Resolved) -> str:
    """The template with {{kit}}, {{home}}, and {{guard_sha256}} filled through plistlib, so
    a path holding & or < stays valid XML. The hash makes the plist differ once an update
    changes the guard's script, so install restarts it and doctor flags a guard still
    running the old one."""
    kit, home = os.path.expanduser(str(resolved["kit"])), str(Path.home())
    digest = hashlib.sha256((Path(kit) / "hooks" / "agent_memory_guard.py").read_bytes()).hexdigest()

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if not isinstance(value, str):
            return value
        return value.replace("{{kit}}", kit).replace("{{home}}", home).replace("{{guard_sha256}}", digest)

    return plistlib.dumps(fill(plistlib.loads(TEMPLATE.read_bytes()))).decode()


_read = launchd._read


def loaded() -> Optional[bool]:
    """Whether launchd has the guard, or None when launchctl couldn't say: only its
    no-such-service status counts as absent, so a failed query never passes for a stop."""
    return AGENT.loaded()


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
    Adds each file to write to writes. Raises ValueError as _read does, and when launchctl
    can't say whether the guard is loaded, so a failed start never removes the plist of a
    guard that's still running."""
    if not hookset.guard_wanted(resolved):
        stops, owned = launchd.plan(AGENT, None, owned, writes)
        return [("guard", path, f"{detail}: its hook isn't selected", start) for path, detail, start in stops], owned
    agent, _ = launchd.plan(AGENT, plist_text(resolved), owned, writes)
    changes: List[Tuple[str, Path, str, bool]] = [("guard", path, detail, start) for path, detail, start in agent]
    limit = shell_limit()
    if limit is None or limit > LIMIT:
        env = _read(zshenv())
        if env is None or LIMIT_LINES not in env:
            writes[zshenv()] = (env or "") + ("\n" if env and not env.endswith("\n") else "") + LIMIT_LINES
            changes.append(("shell-limit", zshenv(), f"caps agent shells at {LIMIT:,} user processes", False))
    return changes, True


def start(path: Path) -> None:
    """(Re)loads the agent from its plist, path, so a changed plist takes effect. When
    launchd won't load it, the plist goes too, so the next install writes it and tries
    again instead of trusting whatever guard is still running."""
    launchd._load(LABEL, path)


def unload() -> None:
    """Stops the agent. Raises OSError while launchd still has it, or can't say."""
    AGENT.unload()


def stop(path: Path) -> None:
    """Stops the agent and removes its plist, path. Raises OSError while launchd still has it."""
    AGENT.unload()
    launchd._remove(path)


def problems(resolved: Resolved, limit: Optional[int]) -> List[str]:
    """What doctor reports, given shell_limit()'s probe: one line per missing, stale, or
    ineffective piece; none when it's not wanted."""
    if not hookset.guard_wanted(resolved):
        return []
    lines = launchd.problems(AGENT, plist_text(resolved))
    if limit is None or limit > LIMIT:
        got = "none" if limit is None else f"{limit:,}"
        lines.append(f"a new agent shell gets no process limit of {LIMIT:,} or less (it gets {got}); "
                     f"check {zshenv()}")
    return lines

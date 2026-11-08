"""The skills CLI (`npx skills`), which installs and updates skills (plan D9), as
`addystack update` runs it and doctor names it in a fix.

Every call passes `-g -y`, so it runs without a terminal, the way an agent runs it. Its
lock file, which records each skill's source, is `$XDG_STATE_HOME/skills/.skill-lock.json`,
or `~/.agents/.skill-lock.json` without XDG_STATE_HOME (skills v1.7.6
`getSkillLockPath`). `ADDYSTACK_SKILLS_CLI` overrides the command, for tests that run
without the network.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT = "npx -y skills"
# The skill that carries the tool, whose lock entry names the kit's source.
KIT_SKILL = "addystack"
# Each enabled host's skill folder: Claude Code's, and the one Codex and the skills CLI's
# universal install share.
FOLDERS = {"claude": "~/.claude/skills", "codex": "~/.agents/skills"}


def command() -> List[str]:
    """The skills CLI as an argv prefix."""
    return shlex.split(os.environ.get("ADDYSTACK_SKILLS_CLI", DEFAULT))


def lock_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME")
    return Path(state, "skills", ".skill-lock.json") if state else Path("~/.agents/.skill-lock.json").expanduser()


def locked() -> Dict[str, Dict[str, Any]]:
    """Each globally installed skill's lock entry, by name; empty without a readable lock."""
    try:
        data = json.loads(lock_path().read_text())
    except (OSError, ValueError):
        return {}
    skills = data.get("skills") if isinstance(data, dict) else None
    return {name: entry for name, entry in skills.items() if isinstance(entry, dict)} if isinstance(skills, dict) else {}


def source(lock: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """The kit's source: the one the lock records for the `addystack` skill itself, which
    carries the tool. None without that entry. A skill of the same name from another
    repo doesn't count, however many there are."""
    entry = lock.get(KIT_SKILL, {})
    return entry["source"] if isinstance(entry.get("source"), str) else None


def add_source(lock: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """The kit's source as `add` takes it: with `#ref` when the kit was installed from a
    ref, as `npx skills add owner/repo#feature` records it, so added skills come from the
    same branch or tag. None without the addystack skill's entry."""
    kit = source(lock)
    ref = lock[KIT_SKILL].get("ref") if kit else None
    return f"{kit}#{ref}" if kit and isinstance(ref, str) and ref else kit


def from_source(lock: Dict[str, Dict[str, Any]], kit_source: str) -> List[str]:
    """The installed skills whose source is kit_source, in name order."""
    return sorted(name for name, entry in lock.items() if entry.get("source") == kit_source)


def add(kit_source: str, names: List[str]) -> List[str]:
    return [*command(), "add", kit_source, "-g", "-y", "--skill", *names]


def remove(names: List[str]) -> List[str]:
    return [*command(), "remove", *names, "-g", "-y"]


def update() -> List[str]:
    return [*command(), "update", "-g", "-y"]

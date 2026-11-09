"""Notes: a person's added steps for one core skill, without copying it (plan D15).

`notes/<skill>.md` in the config's folder (beside the file `ADDYSTACK_CONFIG` names) is
built to `notes/<skill>.md` in the state folder (`ADDYSTACK_STATE`), where the line near
the top of each core skill points. A core skill is a kit skill whose `metadata.layer` is
`primitive` or `orchestrator`; a note for any other name isn't built, and doctor flags it.

The built note starts with a comment naming its source and the sha256 of the skill's
folder (every file but caches) at build time, so doctor can tell when the skill changed
under the note. Build only ever removes files that start with that comment, and builds
nothing while the state folder's notes/ is the config's notes/.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config
import render
import resolved as _resolved
from config import Resolved
import skill_layer
from skill_layer import CORE, layer

_MARK = "<!-- Built by addystack build from "
_HASH = re.compile(r"^<!-- Built by addystack build from .* whose skill had sha256 ([0-9a-f]{64})\.", re.M)


def source_dir() -> Path:
    """The folder a person writes notes in."""
    return config.CONFIG.expanduser().absolute().parent / "notes"


def built_dir() -> Path:
    """The folder build writes notes to, which core skills read."""
    return _resolved.STATE.expanduser().parent / "notes"


def _skill(resolved: Resolved, name: str) -> Optional[Path]:
    """The core skill's SKILL.md in the kit, or None when no core skill has that name."""
    folder = skill_layer.folder(Path(resolved["kit"]), name)
    path = folder / "SKILL.md" if folder else None
    return path if path and layer(path) in CORE else None


def _digest(skill: Path) -> str:
    """sha256 over the skill folder's files and their paths, in a stable order, so a change
    to a reference or script counts as much as one to SKILL.md."""
    digest = hashlib.sha256()
    folder = skill.parent
    for path in sorted(folder.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _aliased() -> bool:
    """True when the built notes folder is the source folder, so building would overwrite
    and remove the person's own notes."""
    return built_dir().resolve() == source_dir().resolve()


def sources() -> List[Path]:
    """Each note a person wrote, by file name."""
    folder = source_dir()
    return sorted(path for path in folder.glob("*.md") if path.is_file()) if folder.is_dir() else []


def built(resolved: Resolved) -> Dict[Path, str]:
    """Each built note's path and text, for the notes whose core skill exists."""
    files = {}
    if _aliased():
        return files
    for note in sources():
        skill = _skill(resolved, note.stem)
        if skill is None:
            continue
        header = (f"{_MARK}{render._home(note)} for {note.stem}, whose skill "
                  f"had sha256 {_digest(skill)}. Edit that file and rerun addystack build. -->")
        files[built_dir() / note.name] = f"{header}\n{note.read_text()}"
    return files


def orphans(resolved: Resolved) -> List[Path]:
    """Each built note build would remove: its source is gone, or its skill isn't core."""
    folder = built_dir()
    if not folder.is_dir() or _aliased():
        return []
    keep = built(resolved)
    return sorted(path for path in folder.glob("*.md")
                  if path not in keep and (path.is_symlink() or path.is_file() and _generated(path)))


def _generated(path: Path) -> bool:
    try:
        return path.read_text().startswith(_MARK)
    except (OSError, UnicodeDecodeError):
        return False



def problems(resolved: Resolved) -> List[Tuple[str, str]]:
    """(problem, fix) for each note whose core skill doesn't exist, and each built note
    whose skill changed since it was built."""
    found = []
    if _aliased():
        return [(f"{built_dir()} is {source_dir()}, so notes aren't built",
                 "make the state folder's notes/ a folder of its own")]
    for note in sources():
        skill = _skill(resolved, note.stem)
        if skill is None:
            found.append((f"{note} names no core skill {note.stem}",
                          f"rename {note} to a core skill's name, or delete it"))
            continue
        try:
            recorded = _HASH.search((built_dir() / note.name).read_text())
        except (OSError, UnicodeDecodeError):
            continue  # not built yet: the built-files check names it
        if recorded and recorded.group(1) != _digest(skill):
            found.append((f"{note.stem} changed since {note} was built",
                          f"reread {note} against {skill}, then run addystack build"))
    return found

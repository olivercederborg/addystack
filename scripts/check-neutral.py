#!/usr/bin/env python3
"""Fails when a kit file names a user or a team, or calls the user he or she.

The kit is a baseline anyone installs, so its text names "the user", never a person, and
holds no team's names or paths (plan D2). NAMES bans a person's name and handle, their
folders and machines, and one team's name and GitHub org. PRONOUNS bans he, him, his,
she, her, and their -self and -s forms, which in this kit only ever mean the user.

Outside the lint (SKIP): history and plans in docs/, eval fixtures in evals/, the
maintainer's scripts in maintainer/, the skills in skills/preferences/ and skills/preset/
(they leave the kit; check-layers.py keeps each skill in its layer's folder), and the
maintainer's own files the live install reads (the root router.md, replies.md, and
taste.md, principles/index.md, and global/). License files and lines of attribution
("Copyright", "Adapted from", a skill's `author:`) name their authors, and KIT_REPO, the
kit's own repo, may appear anywhere, as in the README's install command.

Files: git's tracked and untracked-but-not-ignored files when the kit is a git checkout,
otherwise every file under it (Dagger loads only the kit's own folders). Binary files
are skipped. A link counts once, as its target's path, and a skipped target still counts
when a link outside the skips reaches it, as a skill's references/ link into docs/ does.

Usage: scripts/check-neutral.py   # exit 1 on any problem
"""

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = re.compile(r"olivercederborg|Oliver|Developer/personal|devbox|[Ff]ranklin|hifranklin", re.I)
PRONOUNS = re.compile(r"\b(?:he|him|his|himself|she|her|hers|herself)\b", re.I)
# Only a line that is an attribution, from its start: "Ask Oliver about the Copyright" isn't.
ATTRIBUTION = re.compile(r"^\s*(?:[-*>]\s*)?(?:Copyright\b|Adapted from\b|author:)")
# With the layers that leave the kit: a user's own skills and a team's.
SKIP_DIRS = ("docs/", "evals/", "maintainer/", "global/", ".git/", "skills/preferences/", "skills/preset/")
# The kit's own repo, which install commands name.
KIT_REPO = "olivercederborg/addystack"
# The root files the live install reads until M3, with principles/index.md, the
# maintainer's render of core/principles.md, and this lint and its tests, which spell out
# what they ban.
SKIP_FILES = {"router.md", "replies.md", "taste.md", "principles/index.md",
              "scripts/check-neutral.py", "scripts/test_check_neutral.py"}
LICENSES = re.compile(r"(?:^|/)(?:LICENSE|NOTICE)(?:\.\w+)?$")


def files(root: pathlib.Path):
    """The kit's files as paths relative to root, sorted."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "-co", "--exclude-standard"], cwd=root,
                             capture_output=True, check=True).stdout
        if (root / ".git").exists():
            listed = [p for p in out.decode().split("\0") if p]
            # git lists a linked folder as one entry: read the files behind it too.
            return sorted([p for p in listed if (root / p).is_file()]
                          + [f for p in listed if (root / p).is_symlink() and (root / p).is_dir()
                             for f in _walk(root, root / p)])
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(_walk(root, root))


def _walk(root: pathlib.Path, folder: pathlib.Path):
    """Files under folder, relative to root, following folder links but not a link back
    into a folder above it. A folder reached twice by different paths is listed twice;
    checked() keeps one copy of each real file."""
    found = []
    for top, dirs, names in os.walk(folder, followlinks=True):
        here = pathlib.Path(top)
        if os.path.realpath(top) in {os.path.realpath(up) for up in here.parents if folder in (up, *up.parents)}:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        found += [str(pathlib.Path(top, n).relative_to(root)) for n in names if n != ".DS_Store"]
    return found


def skipped(path: str) -> bool:
    return path.startswith(SKIP_DIRS) or path in SKIP_FILES or bool(LICENSES.search(path))


def checked(root: pathlib.Path):
    """Each file to read, as its real path relative to root, once. A link's target counts
    when the link isn't skipped; a link out of the kit counts as the link."""
    real_root = root.resolve()
    seen = {}
    for path in files(root):
        if skipped(path):
            continue
        real = (root / path).resolve()
        where = str(real.relative_to(real_root)) if real.is_relative_to(real_root) else path
        if (root / path).is_symlink() and where in seen:
            continue
        seen[where] = real
    return sorted(seen.items())


def main(root: pathlib.Path) -> int:
    problems = []
    for path, real in checked(root):
        try:
            text = real.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.split("\n"), 1):
            if ATTRIBUTION.search(line):
                continue
            line = line.replace(KIT_REPO, "")
            found = [m.group(0) for m in NAMES.finditer(line)] + [m.group(0) for m in PRONOUNS.finditer(line)]
            if found:
                problems.append(f"{path}:{number}: {', '.join(dict.fromkeys(found))}")
    if problems:
        print("Kit files say \"the user\" and name no person or team "
              "(a person's name, handle, folders, or machines; a team's name or org; he or she):",
              *problems, sep="\n  ")
        return 1
    print("kit text neutral")
    return 0


if __name__ == "__main__":
    sys.exit(main(ROOT))

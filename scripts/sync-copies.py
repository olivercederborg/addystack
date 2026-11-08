#!/usr/bin/env python3
"""Writes each copy scripts/copies.txt lists from its source, so a skill holds every file it
needs as a real file: the skills CLI (`npx skills add`) skips a symlink that leaves the
skill's folder (plan D17).

The workshop that holds the kit keeps its own copies, into skills that stay there, in
maintainer/copies.txt; when that file exists, its pairs count too.

Each copy is its source with one marker line naming it: first, or second after a shebang.
It keeps the source's mode. Edit the source, then run this script, never the copy.

--check writes nothing and exits 1 naming each copy that differs from its source or is
missing, each symlink left in the kit, each copied script without a sibling it needs
(NEEDS), and each skill with the chat format pointer (scripts/sync-format.sh) whose
references/format.md and views.md aren't listed.

Usage: scripts/sync-copies.py          # write every copy
       scripts/sync-copies.py --check  # exit 1 naming what's out of sync
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIST = "scripts/copies.txt"
WORKSHOP_LIST = "maintainer/copies.txt"
# A copied script runs only with these sources copied into the same folder: github.sh's
# `target` runs verdicts.py beside it, verdicts.py imports evidence.py to record or
# classify, transcripts.py imports t3_child.py, and check-body.mjs runs check-mermaid.mjs.
HOOKS = "skills/primitive/addystack/hooks"
NEEDS = {
    "shared/scripts/github.sh": [f"{HOOKS}/verdicts.py"],
    f"{HOOKS}/verdicts.py": [f"{HOOKS}/evidence.py"],
    f"{HOOKS}/transcripts.py": [f"{HOOKS}/t3_child.py"],
    "skills/primitive/open-pr/scripts/check-body.mjs": ["shared/scripts/check-mermaid.mjs"],
}
# Each skill with the format pointer copies these into references/.
POINTER = "<!-- toolkit-format:start"
FORMAT = ["shared/format.md", "shared/views.md"]
COMMENT = {".md": "<!-- {} -->", ".py": "# {}", ".sh": "# {}", ".mjs": "// {}"}
# Folders the symlink scan skips: git's, and tools' untracked environments.
SKIPPED = {".git", "node_modules", ".venv", "__pycache__", ".dagger/sdk"}


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def listed(root):
    """copies.txt, and the workshop's when it has one, as [(source, destination)], one pair
    per line; `#` starts a comment."""
    pairs, seen = [], set()
    for name in (LIST, WORKSHOP_LIST):
        if name == WORKSHOP_LIST and not (root / name).is_file():
            continue
        for number, line in enumerate((root / name).read_text().splitlines(), 1):
            words = line.split("#", 1)[0].split()
            if not words:
                continue
            if len(words) != 2:
                fail(f"{name}:{number}: want `<source> <destination>`, got {line!r}")
            if words[1] in seen:
                fail(f"{name}:{number}: {words[1]} is listed twice")
            seen.add(words[1])
            pairs.append((words[0], words[1]))
    return pairs


def copied(root, source):
    """The source's text with its marker line, which never changes for a given source."""
    text = (root / source).read_text()
    suffix = pathlib.PurePath(source).suffix
    if suffix not in COMMENT:
        fail(f"{source}: no comment syntax for {suffix or 'a file without a suffix'}; add one to COMMENT")
    marker = COMMENT[suffix].format(f"Copy of {source}, written by scripts/sync-copies.py:"
                                    " edit the source, then run the script.") + "\n"
    if text.startswith("#!"):
        shebang, _, rest = text.partition("\n")
        return f"{shebang}\n{marker}{rest}"
    return marker + text


def symlinks(root):
    """Each symlink under root, outside SKIPPED folders."""
    found = []
    for folder, dirs, files in os.walk(root):
        # A skipped folder is left out whether or not it's a link; os.walk doesn't descend
        # into a linked folder, which is reported below.
        dirs[:] = [d for d in dirs
                   if d not in SKIPPED and os.path.relpath(os.path.join(folder, d), root) not in SKIPPED]
        for name in [*dirs, *files]:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                found.append(os.path.relpath(path, root))
    return sorted(found)


def linked_parents(root, destination):
    """The folders between root and destination that are symlinks, which a write would
    follow out of the kit."""
    path, linked = root, []
    for part in pathlib.PurePosixPath(destination).parent.parts:
        path = path / part
        if path.is_symlink():
            linked.append(str(path.relative_to(root)))
    return linked


def rules(root, pairs):
    """Each copy a NEEDS entry or the format pointer asks for that copies.txt lacks."""
    have, missing = set(pairs), []
    for source, destination in pairs:
        folder = pathlib.PurePosixPath(destination).parent
        for need in NEEDS.get(source, []):
            beside = str(folder / pathlib.PurePosixPath(need).name)
            if (need, beside) not in have:
                missing.append(f"{destination} needs a copy of {need} at {beside}")
    for skill in sorted(root.glob("skills/*/*/SKILL.md")):
        if POINTER in skill.read_text():
            name = skill.parent.relative_to(root).as_posix()
            for source in FORMAT:
                if (source, f"{name}/references/{pathlib.PurePath(source).name}") not in have:
                    missing.append(f"{name} has the format pointer, so {LIST} needs"
                                   f" {source} {name}/references/{pathlib.PurePath(source).name}")
    return missing


def main(argv):
    if argv not in ([], ["--check"]):
        fail(f"usage: {sys.argv[0]} [--check]")
    check = argv == ["--check"]
    pairs = listed(ROOT)
    # Refuse before writing anything: a linked folder would send a write outside the kit.
    escapes = sorted({link for _, destination in pairs for link in linked_parents(ROOT, destination)})
    if escapes:
        print(f"Out of sync with {LIST}; these folders are symlinks, so no copy was written:",
              *[f"{link} (a symlink: make it a real folder)" for link in escapes], sep="\n  ")
        return 1
    stale = []
    for source, destination in pairs:
        path, want = ROOT / destination, copied(ROOT, source)
        mode = (ROOT / source).stat().st_mode & 0o777
        if path.is_symlink() or not path.is_file():
            reason = "missing"
        elif path.read_text() != want:
            reason = f"differs from {source}"
        elif path.stat().st_mode & 0o777 != mode:
            reason = f"mode differs from {source}'s {mode:o}"
        else:
            continue
        stale.append(f"{destination} ({reason})")
        if not check:
            if path.is_symlink():
                path.unlink()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(want)
            os.chmod(path, mode)
    problems = rules(ROOT, pairs)
    problems += [f"{link} (a symlink: list its target in {LIST} instead)" for link in symlinks(ROOT)]
    if check and stale:
        problems = [*stale, *problems]
    if problems:
        print(f"Out of sync with {LIST}; edit sources or the list, then run scripts/sync-copies.py:",
              *problems, sep="\n  ")
        return 1
    if not check:
        print(f"synced {len(stale)} of {len(pairs)} copies", *stale, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

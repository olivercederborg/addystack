#!/usr/bin/env python3
"""Fails when a skill names a skill in a higher layer, declares no layer, or sits in
another layer's folder.

Each SKILL.md declares `metadata.layer` in its frontmatter, and its folder is
skills/<layer>/<skill>/. From the bottom the core
layers are primitive < orchestrator < optional, and a skill names only skills in its own
layer or a lower one. `preferences` (a user's own skills) and `preset` (a team's, until
they leave the kit) may name anything, and no core skill may name one of them.

A skill's text is every Markdown file in its folder, following its links, so a shared
file a skill links into references/ counts as that skill's text. The addystack skill also
carries the kit's tool, whose router template and hooks name every layer, so its text is
its SKILL.md and references/ only. A name counts as a
whole word in any case, even one that's an English word, such as coordinator.

Usage: scripts/check-layers.py   # exit 1 on any problem
"""

import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack" / "lib"))
from skill_layer import layer  # noqa: E402

# The skill that carries the tool; its text is its SKILL.md and references/.
TOOL_SKILL = "addystack"
RANK = {"primitive": 0, "orchestrator": 1, "optional": 2, "preferences": 3, "preset": 3}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def texts(folder: pathlib.Path):
    """Every Markdown file in the skill's folder, a linked file read through its link,
    once per real file."""
    seen = set()
    for top, dirs, files in os.walk(folder, followlinks=True):
        here = pathlib.Path(top)
        # Not a link back into a folder above it.
        if os.path.realpath(top) in {os.path.realpath(up) for up in here.parents if folder in (up, *up.parents)}:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            path = pathlib.Path(top, name)
            if path.suffix == ".md" and path.exists() and path.resolve() not in seen:
                seen.add(path.resolve())
                yield path


def finder(name: str):
    """A function from a line to whether it names this skill: the name as a whole word, in
    any case. Even a name that's an English word counts, such as coordinator: the lint
    only checks names in a higher layer than the skill that uses them, and nothing ranks
    below a primitive, so a plain word like "build" never needs this. A higher skill whose
    name is a word gets no exception, since prose can invoke it in any phrasing or wrap."""
    pattern = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", re.I)
    return lambda line: bool(pattern.search(line))


def main(root: pathlib.Path) -> int:
    skills = {skill.parent.name: skill for skill in sorted(root.glob("skills/*/*/SKILL.md"))}
    layers, problems = {}, []
    for name, skill in skills.items():
        found, where = layer(skill), skill.relative_to(root)
        if found not in RANK:
            problems.append(f"{where}: metadata.layer is {found!r}; use one of {', '.join(RANK)}")
            continue
        layers[name] = found
        if where.parts[1] != found:
            problems.append(f"{where}: metadata.layer is {found!r}; move the folder to skills/{found}/{name}/")
    finders = {name: finder(name) for name in layers}
    # (real file, line number, named skill) -> [(skill, its layer)], so a shared file shows once.
    hits = {}
    for name, own in layers.items():
        higher = [other for other in layers if RANK[layers[other]] > RANK[own]]
        if not higher:
            continue
        folder = skills[name].parent
        paths = [folder / "SKILL.md", *texts(folder / "references")] if name == TOOL_SKILL else texts(folder)
        for path in paths:
            real = path.resolve()
            where = real.relative_to(root.resolve()) if real.is_relative_to(root.resolve()) else real
            for number, line in enumerate(path.read_text().split("\n"), 1):
                for other in higher:
                    if finders[other](line):
                        hits.setdefault((str(where), number, other), []).append(f"{name} ({own})")
    for (where, number, other), by in sorted(hits.items()):
        more = f" and {len(by) - 1} more" if len(by) > 1 else ""
        problems.append(f"{where}:{number}: {by[0]}{more} names {other} ({layers[other]})")
    if problems:
        print("A skill names only skills in its own layer or a lower one "
              "(primitive < orchestrator < optional < preferences, preset):", *problems, sep="\n  ")
        return 1
    print("skill layers valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(ROOT))

#!/usr/bin/env python3
"""Puts shared/notes-line.md's line near the top of every core skill (plan D15).

A core skill is one whose `metadata.layer` is `primitive` or `orchestrator`. Its line
goes under the title, or first when the skill has none, and counts as near the top
within the first TOP lines after the frontmatter and before the first `## ` section,
where it survives Claude Code's compaction, which keeps a skill's first 5,000 tokens. A
skill in any other layer carries no notes line. The write mode also replaces a line that
starts with `**Notes**:` near the top, so an older wording can't stay behind.

Usage: scripts/sync-notes.py           # write
       scripts/sync-notes.py --check   # exit 1 naming each skill that differs
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "primitive" / "addystack" / "lib"))
from skill_layer import CORE, layer  # noqa: E402

TOP = 8
PREFIX = "**Notes**:"


def _split(text):
    """(frontmatter lines with both fences, body lines)."""
    lines = text.split("\n")
    end = lines.index("---", 1) + 1 if lines[0] == "---" and "---" in lines[1:] else 0
    return lines[:end], lines[end:]


def _top(body):
    """The indexes of the body's lines near the top."""
    for index, line in enumerate(body[:TOP]):
        if line.startswith("## "):
            return range(index)
    return range(min(TOP, len(body)))


def synced(text, line, core):
    """text with the notes line where it belongs: under the title for a core skill, gone
    from any other skill."""
    head, body = _split(text)
    near = set(_top(body))
    if core and line in [body[index] for index in near]:
        return text
    kept, skip_blank = [], False
    for index, current in enumerate(body):
        if current == line or (index in near and current.startswith(PREFIX)):
            skip_blank = True
            continue
        if skip_blank and not current:
            skip_blank = False
            continue
        skip_blank = False
        kept.append(current)
    if core:
        start = next((index for index, current in enumerate(kept) if current), len(kept))
        if start < len(kept) and kept[start].startswith("# "):
            rest = start + 1
            while rest < len(kept) and not kept[rest]:
                rest += 1
            kept = kept[:start + 1] + ["", line, ""] + kept[rest:]
        else:
            kept = [line, ""] + kept[start:]
    return "\n".join(head + kept)


def main(check):
    line = (ROOT / "shared" / "notes-line.md").read_text().strip()
    stale = []
    for skill in sorted(ROOT.glob("skills/*/*/SKILL.md")):
        text = skill.read_text()
        fixed = synced(text, line, layer(skill) in CORE)
        if fixed != text:
            stale.append(str(skill.relative_to(ROOT)))
            if not check:
                skill.write_text(fixed)
    if check and stale:
        print("The notes line from shared/notes-line.md belongs near the top of each core skill, and in no "
              "other; run scripts/sync-notes.py:", *stale, sep="\n  ")
        return 1
    print("notes lines in sync" if check else "synced", *stale, sep="\n  ")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        sys.exit(f"usage: {sys.argv[0]} [--check]")
    sys.exit(main(sys.argv[1:] == ["--check"]))

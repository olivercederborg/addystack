#!/usr/bin/env python3
"""Writes the addystack skill's core/skills.json: every skill in the kit with its
`metadata.layer` (plan D9).

`addystack update` reads it from the installed kit to add the core skills a release adds
and remove the skills it dropped, and doctor to check the core skills are installed; an
install made with the skills CLI holds only the skills it chose, so neither can list the
release's folders.

Usage: scripts/sync-skill-list.py           # write
       scripts/sync-skill-list.py --check   # exit 1 when it differs from the skill folders
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The addystack skill's folder, where the release list lives.
KIT = ROOT / "skills" / "primitive" / "addystack"
sys.path.insert(0, str(KIT / "lib"))
from skill_layer import RELEASE, listed  # noqa: E402


def main(check):
    path = KIT / RELEASE
    shown = path.relative_to(ROOT)
    text = json.dumps({"skills": listed(ROOT)}, indent=2) + "\n"
    current = path.read_text() if path.is_file() else None
    if current == text:
        print("skill list in sync")
        return 0
    if check:
        print(f"{shown} differs from the skill folders; run scripts/sync-skill-list.py", file=sys.stderr)
        return 1
    path.write_text(text)
    print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))

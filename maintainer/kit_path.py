#!/usr/bin/env python3
"""Where the workshop finds the addystack kit, which lives in its own repo (plan D18):
ADDYSTACK_KIT, a checkout of olivercederborg/addystack, by default
~/Developer/personal/addystack. The evals, maintainer/, and the workshop skills' tests all
read it here, and nowhere else names the default.

  maintainer/kit_path.py         # print the checkout
  maintainer/kit_path.py --tool  # print the addystack tool's folder in it
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT = "~/Developer/personal/addystack"
TOOL = Path("skills", "primitive", "addystack")


def repo() -> Path:
    """The kit's checkout; exits naming the fix when it isn't one."""
    path = Path(os.environ.get("ADDYSTACK_KIT") or DEFAULT).expanduser().resolve()
    if not (path / TOOL / "bin" / "addystack").is_file():
        raise SystemExit(f"no addystack checkout at {path}: clone olivercederborg/addystack there, "
                         "or set ADDYSTACK_KIT to one")
    return path


def tool() -> Path:
    """The addystack skill's folder, which holds bin/, lib/, and hooks/."""
    return repo() / TOOL


def skill(name: str) -> Path:
    """A kit skill's folder, whatever its layer."""
    found = sorted(repo().glob(f"skills/*/{name}/SKILL.md"))
    if not found:
        raise SystemExit(f"the addystack checkout at {repo()} has no skill {name}")
    return found[0].parent


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--tool"]):
        print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
        sys.exit(2)
    print(tool() if sys.argv[1:] else repo())

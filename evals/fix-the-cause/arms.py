#!/usr/bin/env python3
"""Builds one --variant folder per arm: the router and principles index that a live Claude
Code session loads through ~/.claude/CLAUDE.md, rendered from one addystack revision, with
that revision's principle files behind the index's pointers. A live session opens a
principle file only when its index line sends it there, so the arm does the same.

Usage: evals/fix-the-cause/arms.py KIT_REPO OUT ARM=REV [ARM=REV...] [--typed ARM]
       evals/fix-the-cause/arms.py KIT_REPO --check   # current main renders as the live files
--typed ARM adds the fix-kind rule R101 tested to that arm's turn blocks (not shipped).
"""
import pathlib
import subprocess
import sys

TASTE = " What good code and UI look like:\n`~/.config/addystack/taste.md`."
ADDYSTACK = "~/Developer/personal/addystack/skills/primitive/addystack/bin/addystack"
LIVE_KIT = "~/Developer/personal/addystack/skills/primitive/addystack"
CORE = "skills/primitive/addystack/core/"
TYPED = """

## Fix kind on a pick (enforced)

Each option in your reply's turn block that picks a fix carries `"fix": "cause"` or
`"fix": "stopgap"`, and a stopgap carries `"why"`, one of `prod-hurts-now`,
`other-owner`, or `cause-fix-own-pr` (the cause fix is offered as its own PR beside it).
A Stop hook sends back a reply whose option `a` picks a fix without them.
"""


def show(repo, rev, path):
    return subprocess.check_output(["git", "-C", repo, "show", f"{rev}:{path}"], text=True)


def render(repo, rev, kit):
    fill = lambda t: (t.replace("{{user}}", "Oliver").replace("{{kit}}", kit)
                       .replace("{{taste}}", TASTE).replace("{{addystack}}", ADDYSTACK))
    return fill(show(repo, rev, CORE + "router.md")), fill(show(repo, rev, CORE + "principles.md"))


def build(repo, out, arm, rev, typed):
    kit = out / "kits" / arm
    (kit / "principles").mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(["git", "-C", repo, "ls-tree", "--name-only", rev,
                                     "skills/primitive/addystack/principles/"], text=True).split()
    for name in names:
        (kit / "principles" / pathlib.Path(name).name).write_text(show(repo, rev, name))
    router, principles = render(repo, rev, str(kit))
    router = router.replace("@principles.md", principles.strip())
    variant = out / "variants" / arm
    variant.mkdir(parents=True, exist_ok=True)
    (variant / "SKILL.md").write_text(f"""---
name: addystack-router
description: Oliver's always-loaded router and principles index for this run.
---

This run replaces the router and principles index that ~/.claude/CLAUDE.md imports from
~/.local/state/addystack/ with the text below. Follow it in place of those, and open a
principle file only as its index line says, from {kit}/principles/.

{router.strip()}{TYPED if typed else ""}
""")


def main(argv):
    repo = argv[0]
    if argv[1:] == ["--check"]:
        router, principles = render(repo, "origin/main", LIVE_KIT)
        live = pathlib.Path("~/.local/state/addystack").expanduser()
        router = router.replace("@principles.md", "@~/.local/state/addystack/principles.md")
        same = router == (live / "router.md").read_text() and principles == (live / "principles.md").read_text()
        print("matches the live router and principles" if same else "differs from the live files")
        return 0 if same else 1
    out, rest = pathlib.Path(argv[1]).resolve(), argv[2:]
    typed = rest[rest.index("--typed") + 1] if "--typed" in rest else None
    for pair in (a for a in rest if "=" in a):
        arm, rev = pair.split("=", 1)
        build(repo, out, arm, rev, arm == typed)
        print(arm, rev)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

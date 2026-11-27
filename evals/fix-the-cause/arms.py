#!/usr/bin/env python3
"""Builds one --variant folder per arm: the router and principles index that a live Claude
Code session loads through ~/.claude/CLAUDE.md, rendered from one addystack revision, with
that revision's principle files behind the index's pointers. A live session opens a
principle file only when its index line sends it there, so the arm does the same. The
user's name, CLI path, taste line, and excluded principles come from this machine's
addystack build, through the kit's own renderer, so the arms match whoever runs them.

Usage: evals/fix-the-cause/arms.py KIT_REPO OUT ARM=REV [ARM=REV...] [--typed ARM]
       evals/fix-the-cause/arms.py KIT_REPO --check   # current main renders as the live files
--typed ARM adds the fix-kind rule R101 tested to that arm's turn blocks (not shipped).
"""
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "maintainer"))
import kit_path  # noqa: E402
sys.path[:0] = [str(kit_path.tool() / "lib"), str(kit_path.tool() / "hooks")]
import hookset  # noqa: E402
import render as kit_render  # noqa: E402
import resolved  # noqa: E402

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


def live():
    """This machine's built config (resolved.json), which the live router was rendered from."""
    return json.loads(resolved.STATE.expanduser().read_text())


def render(repo, rev, kit, built):
    """rev's router and principles part, filled as render.instructions fills them from
    `built`, with {{kit}} as `kit`. The principles part is None when that build has none:
    preset `none` without a taste file."""
    values = {"user": built["identity"]["name"], "kit": kit, "addystack": f"{hookset._kit(built)}/bin/addystack"}
    router = kit_render._fill(show(repo, rev, CORE + "router.md"), values)
    judgment = built["judgment"]
    if judgment["principles"]["preset"] != "none":
        with tempfile.TemporaryDirectory() as core:
            pathlib.Path(core, "principles.md").write_text(show(repo, rev, CORE + "principles.md"))
            return router, kit_render._principles(built, pathlib.Path(core), values)
    if judgment["taste"]:
        return router, f"# Taste\n\nWhat good code and UI look like: `{kit_render._home(pathlib.Path(judgment['taste']))}`.\n"
    return kit_render._expand(router, {}, str), None


def build(repo, out, arm, rev, typed, built):
    kit = out / "kits" / arm
    (kit / "principles").mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(["git", "-C", repo, "ls-tree", "--name-only", rev,
                                     "skills/primitive/addystack/principles/"], text=True).split()
    for name in names:
        (kit / "principles" / pathlib.Path(name).name).write_text(show(repo, rev, name))
    router, principles = render(repo, rev, str(kit), built)
    router = router.replace("@principles.md", (principles or "").strip())
    variant = out / "variants" / arm
    variant.mkdir(parents=True, exist_ok=True)
    (variant / "SKILL.md").write_text(f"""---
name: addystack-router
description: {built["identity"]["name"]}'s always-loaded router and principles index for this run.
---

This run replaces the router and principles index that ~/.claude/CLAUDE.md imports from
~/.local/state/addystack/ with the text below. Follow it in place of those, and open a
principle file only as its index line says, from {kit}/principles/.

{router.strip()}{TYPED if typed else ""}
""")


def main(argv):
    repo, built = argv[0], live()
    if argv[1:] == ["--check"]:
        state = resolved.STATE.expanduser().parent
        router, principles = render(repo, "origin/main", kit_render._home(pathlib.Path(built["kit"])), built)
        router = router.replace("@principles.md", f"@{kit_render._home(state / 'principles.md')}")
        live_principles = state / "principles.md"
        same = router == (state / "router.md").read_text() and principles == (
            live_principles.read_text() if live_principles.exists() else None)
        print("matches the live router and principles" if same else "differs from the live files")
        return 0 if same else 1
    out, rest = pathlib.Path(argv[1]).resolve(), argv[2:]
    typed = rest[rest.index("--typed") + 1] if "--typed" in rest else None
    for pair in (a for a in rest if "=" in a):
        arm, rev = pair.split("=", 1)
        build(repo, out, arm, rev, arm == typed, built)
        print(arm, rev)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

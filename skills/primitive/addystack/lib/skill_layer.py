"""metadata.layer from a SKILL.md's frontmatter, shared by scripts/check-layers.py,
scripts/check-neutral.py, scripts/sync-notes.py, and lib/notes.py, so all read the same
field the same way; and the release's skill list, core/skills.json, that
scripts/sync-skill-list.py writes from it and `addystack update` and doctor read."""

import json
import pathlib
import re


def layer(skill: pathlib.Path):
    """The `layer:` that's a direct child of the frontmatter's top-level `metadata:` map,
    or None. A `layer:` nested deeper, as under `metadata.extension`, doesn't count."""
    lines = skill.read_text().split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return None
    inside, child_indent = False, None
    for line in lines[1:lines.index("---", 1)]:
        if not line.strip() or line.lstrip().startswith("#"):
            # Blank and comment lines set no indent: YAML ignores them.
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent == 0:
            inside, child_indent = line.rstrip() == "metadata:", None
            continue
        if not inside:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        match = re.match(r"\s+layer:\s*(['\"]?)([\w-]+)\1\s*(?:#.*)?$", line)
        if match:
            return match.group(2)
    return None


# Where a release lists its skills by layer, so `addystack update` and doctor know them in
# an install that holds only some: the skills CLI copies each skill folder on its own.
RELEASE = pathlib.Path("core") / "skills.json"
CORE = ("primitive", "orchestrator")
# The layers a release ships. A user's own skills and a team's install from their own repos.
SHIPPED = (*CORE, "optional")
# Each core skill's earlier name, {old: new}, so a rename keeps what a user had under the old
# one: a note keeps applying (lib/notes.py), update installs the new name only where the old
# one was installed (bin/addystack), and install moves a link to the old folder (lib/reconcile.py).
RENAMED = {"review-teammate-pr": "review-code"}


def current(name: str) -> str:
    """The skill's name now: name itself, or what it was renamed to."""
    return RENAMED.get(name, name)


def listed(root: pathlib.Path):
    """{skill: layer} for each skill folder under root's skills/<layer>/ whose layer a release
    ships, from its SKILL.md, in name order."""
    found = {skill.parent.name: layer(skill)
             for skill in sorted(root.glob("skills/*/*/SKILL.md"), key=lambda skill: skill.parent.name)}
    return {name: value for name, value in found.items() if value in SHIPPED}


def folder(kit: pathlib.Path, name: str):
    """The skill's folder beside the kit, which is the addystack skill's folder: its sibling,
    as the skills CLI installs them, or in a checkout's skills/<layer>/. None when no skill
    has that name."""
    found = [kit.parent / name, *sorted(kit.parent.parent.glob(f"*/{name}"))]
    return next((path for path in found if (path / "SKILL.md").is_file()), None)


def released(kit: pathlib.Path):
    """{skill: layer} from the kit's RELEASE file, or None when it's missing or unreadable."""
    return read_list(kit / RELEASE)


def read_list(path: pathlib.Path):
    """{skill: layer} from a file shaped like RELEASE, or None when it's missing or
    unreadable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        return None
    return {name: value for name, value in skills.items() if isinstance(value, str)}


def core(skills):
    """The names in a {skill: layer} map whose layer is core."""
    return [name for name, value in skills.items() if value in CORE]

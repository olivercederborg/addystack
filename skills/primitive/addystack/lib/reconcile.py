"""Brings each host's hooks and instruction file in line with a Resolved config (plan D9).

`addystack install` runs this before build, and `addystack update` ends with an install.
It never installs or links a skill: skills install with `npx skills add`, and doctor
accepts that install or a maintainer's linked checkout.

Skill links: a maintainer links skills from the checkout, so once the kit drops a skill,
its links stay in each host's skill folder, dangling or at a folder that only untracked
files such as __pycache__ keep. So in both hosts' skill folders, enabled or not, since one
host's link can lead through the other's, install removes a link with no SKILL.md behind it
that resolves, itself or through another link, into the kit checkout's skills/<layer>/ (or
the checkout the last build recorded, when it moved), when the kit has no skill of that
name, once each when one host's folder is the other's. Any other link stays, a link into a
previous checkout that still has the skill's SKILL.md too: that checkout can be another
repo the user still links skills from, as the workshop was before the kit moved out. In an npx skills install, update removes a skill the release no longer
lists as core (_update_skills); one that was never core stays.

Hooks: each enabled host's settings get the hooks hookset.select picks, merged with
hookset.merge into Claude Code's settings.json `hooks` key and Codex's
~/.codex/hooks.json (hookset.settings_path), so every hook addystack didn't install stays where it
is. A hook addystack installed is one the ledger records, at installed.json in the state
folder (`ADDYSTACK_STATE`), or one a manifest entry renders for this kit, or one that runs
a manifest script from the kit path the last build recorded, when the checkout has moved
(hookset.owner). So a user's hook on another script in the kit's hooks folder stays, and
each of addystack's is removed once it's no longer selected. A disabled host's earlier hooks are removed too, when its file exists.
A settings file that isn't a JSON object stops the run before anything is written.

Instructions: before build replaces Claude Code's CLAUDE.md or ~/.codex/AGENTS.md for an
enabled host, text there that addystack didn't build (its first line isn't a build header)
moves into the user's instructions file: the one the config's `instructions` names, or
`global.md` beside the config, created or appended to, never overwritten. Text the file
already holds isn't added again, so a second install, or the same text in both hosts'
files, adds it once. Appended text that doesn't open with a `# ` heading gets one naming
its source, so it doesn't join the file's last section. When the config names no
instructions file, install sets `"instructions": "global.md"` in it, so the build carries
the text; with no config yet, the build reads `global.md` beside where it would be
(config.load_layers), and `addystack init` names it.

Agent: Claude Code reads subagents from the agents/ folder in its own folder, and only a
`work-verifier` subagent can record a Done verdict, but `npx skills add` installs the agent
inside verify-work's folder. So when the claude host is enabled, install links agent() to
that copy in Claude's skill folder (agent_source()), replacing a link or filling a missing path. A file
or folder there is the user's, so install leaves it and reports it; so does a verify-work
without agent_source(), since a link to it would dangle. Without verify-work, nothing forks
into the agent, so install does nothing, and a disabled host's link stays too. No ledger
entry: a link is always install's to replace and anything else never is.

Commands: the hooks in COMMANDS send a Claude Code command, so while hookset selects any of
them for Claude Code, install links that command in Claude's commands/ folder to the kit's
copy, as it links the agent, and once none is selected, removes a link to the kit's copy, or
to the copy in the kit path the last build recorded, when the checkout has moved.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import config
import hookset
import render
import resolved as _resolved
import skill_layer
import skills_cli
from config import Resolved

LEDGER = _resolved.STATE.parent / "installed.json"
# Each command file in the kit's commands/ folder, and the hooks that send it.
COMMANDS = {"cleanest.md": ("cleanest-ask", "cleanest-ask-impl")}


def agent() -> Path:
    """Where Claude Code finds the verify-work fork's subagent."""
    return config.claude_home() / "agents" / "work-verifier.md"


def agent_source() -> Path:
    """The agent's copy the skills CLI installs with verify-work, in Claude Code's skill folder."""
    return skills_cli.folder("claude") / "verify-work" / "agents" / "work-verifier.md"


# The first line of a file addystack built: `addystack build`'s, and scripts/build-global.py's
# before it.
_BUILT = ("<!-- Built by addystack build", "<!-- Built by scripts/build-global.py")
_GLOBAL = config.GLOBAL


@dataclass(frozen=True)
class Change:
    """One change run() makes, or plan() would make; with left, a path it reports but
    won't touch."""
    kind: Literal["hooks", "adopt-instructions", "agent", "command", "skill-link", "renamed-skill"]
    target: Path
    detail: str
    left: bool = False
    # For a command: what install links target to, or None to remove the link. For a
    # renamed skill: its new folder, which a link of its new name points at.
    source: Optional[Path] = None


def run(resolved: Resolved) -> List[Change]:
    """Every change needed, made. Raises ValueError, before writing anything, when a
    settings file or the config can't be read or edited safely."""
    changes, writes = plan(resolved)
    for path, text in writes.items():
        _write(path, text)
    for change in changes:
        if change.kind == "agent" and not change.left:
            _link(change.target, agent_source())
        elif change.kind == "command" and not change.left and change.source:
            _link(change.target, change.source)
        elif change.kind in ("command", "skill-link") and not change.left:
            os.unlink(change.target)
        elif change.kind == "renamed-skill" and not change.left:
            _link(change.target.with_name(change.source.name), change.source)
            os.unlink(change.target)
    return changes


def plan(resolved: Resolved) -> Tuple[List[Change], Dict[Path, str]]:
    """Every change needed, and the text each file it writes would hold, the ledger's
    included, writing nothing; so install --dry-run can preview the build from that state
    (config.planned). Raises as run() does."""
    writes: Dict[Path, str] = {}
    changes = _adopt(resolved, writes)
    ledger = _ledger()
    recorded: Dict[str, List[List[str]]] = {}
    for runtime in hookset.RUNTIMES:
        change, pairs = _hooks(resolved, runtime, ledger.get(runtime, []), writes)
        changes += [change] if change else []
        if pairs:
            recorded[runtime] = pairs
    wanted = {"version": 1, "hooks": recorded}
    if _read_json(LEDGER.expanduser()) != wanted:
        writes[LEDGER.expanduser()] = json.dumps(wanted, indent=2) + "\n"
    agent = _agent(resolved)
    return changes + ([agent] if agent else []) + _commands(resolved) + _renamed_skills(resolved) + _skill_links(resolved), writes


def _skill_links(resolved: Resolved) -> List[Change]:
    """The removal of each host's link to a skill the kit's checkout dropped; see Skill
    links above."""
    kit = Path(resolved["kit"])
    trees = {_place(tree) for tree in map(_skill_tree, [str(kit), *_moved_kits(resolved)]) if tree}
    changes, seen = [], set()
    for host in ("claude", "codex"):
        folder = skills_cli.folder(host)
        if not folder.is_dir():
            continue
        for link in sorted(folder.iterdir()):
            entry = (_place(str(folder)), link.name)
            if entry in seen or not link.is_symlink() or (link / "SKILL.md").is_file() \
                    or skill_layer.folder(kit, link.name):
                continue
            seen.add(entry)
            gone = Path(os.path.realpath(link))
            if _place(str(gone.parent.parent)) in trees:
                changes.append(Change("skill-link", link, f"removes it: the kit has no {link.name} skill at "
                                                          f"{render._home(gone)}"))
    return changes


def _skill_tree(kit: str) -> Optional[str]:
    """A kit checkout's skills/ folder, the addystack skill's grandparent, or None for a kit
    the skills CLI installed, whose skills it removes itself."""
    tree = Path(os.path.abspath(os.path.expanduser(kit))).parents[1]
    return str(tree) if tree.name.casefold() == "skills" else None


def _place(path: str) -> Any:
    """What names one folder however its path is spelled, in case or through links: its
    device and inode, or for a folder that's gone, its resolved path."""
    try:
        info = os.stat(path)
    except OSError:
        return os.path.realpath(path)
    return info.st_dev, info.st_ino


def _commands(resolved: Resolved) -> List[Change]:
    """The command links' changes: a link for each command a selected hook sends, and the
    removal of a link to the kit's copy once none of its hooks is selected."""
    selected = {entry.id for entry in hookset.select(resolved, "claude")} if resolved["hosts"].get("claude") else set()
    changes = []
    for name, hooks in COMMANDS.items():
        on = [hook for hook in hooks if hook in selected]
        link, source = config.claude_home() / "commands" / name, Path(resolved["kit"]) / "commands" / name
        earlier = os.readlink(link) if link.is_symlink() else None
        ours = {str(source), *(os.path.join(os.path.expanduser(kit), "commands", name) for kit in _moved_kits(resolved))}
        if not on:
            if earlier in ours:
                changes.append(Change("command", link, f"removes it: {' and '.join(hooks)} are off"))
        elif earlier is None and os.path.lexists(link):
            changes.append(Change("command", link, f"a file addystack didn't link, left as is; {' and '.join(on)} needs it to "
                                  f"link {render._home(source)}", left=True))
        elif earlier != str(source):
            changes.append(Change("command", link, f"links it to {render._home(source)}"
                                  + (f", not {earlier}" if earlier else ""), source=source))
    return changes


def _renamed_skills(resolved: Resolved) -> List[Change]:
    """Each enabled host's link to a renamed skill's old folder (skill_layer.RENAMED), which a
    linked checkout's update left dangling: install links the new name to the new folder
    beside it and drops the old link. A new name already taken is the user's, so the old link
    is reported and left."""
    # Both hosts can share one folder through a link, and one host's link can lead through
    # the other's: each folder once, and each link goes straight to the folder its chain ended
    # at, renamed, never to whatever another folder holds under the new name.
    folders = dict.fromkeys(skills_cli.folder(host).resolve() for host in ("claude", "codex")
                            if resolved["hosts"].get(host))
    changes = []
    for folder in folders:
        for old, new in skill_layer.RENAMED.items():
            link = folder / old
            if not link.is_symlink() or link.exists():
                continue
            ended = Path(os.path.realpath(link))
            moved = ended.parent / new
            if ended.name != old or not (moved / "SKILL.md").is_file():
                continue
            if os.path.lexists(folder / new):
                changes.append(Change("renamed-skill", link, f"dangles, and {new} is installed already; remove it",
                                      left=True))
            else:
                changes.append(Change("renamed-skill", link, f"{old} is {new} now: links {new} to "
                                      f"{render._home(moved)} in its place", source=moved))
    return changes


def _agent(resolved: Resolved) -> Optional[Change]:
    """The agent link's change, or None when it's in place, the claude host is off, or
    verify-work isn't installed for Claude Code, so nothing forks into it."""
    link, source = agent(), agent_source()
    if not resolved["hosts"].get("claude") or not os.path.lexists(source.parents[1]):
        return None
    if not link.is_symlink() and os.path.lexists(link):
        return Change("agent", link, f"a file addystack didn't link, left as is; move it aside, then run addystack "
                      f"install to link {render._home(source)}", left=True)
    if not source.is_file():
        kit = skills_cli.add_source(skills_cli.locked()) or "<the addystack repo>"
        return Change("agent", link, f"not linked: verify-work has no {render._home(source)}; run npx skills add "
                      f"{kit} -g -y --skill verify-work, then addystack install", left=True)
    if link.is_symlink():
        earlier = os.readlink(link)
        if earlier == str(source):
            return None
        return Change("agent", link, f"links it to {render._home(source)}, not {earlier}")
    return Change("agent", link, f"links it to {render._home(source)}")


def _link(path: Path, source: Path) -> None:
    """Points path at source by renaming a link made beside it, so path never goes
    missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = _beside(path)
    # Made outside the try: when the name is taken, the file there isn't ours to remove.
    partial.symlink_to(source)
    try:
        os.replace(partial, path)
    finally:
        _remove(partial)


def _beside(path: Path) -> Path:
    """A new name beside path for a file or link to rename over it. Random, so it never
    names a file someone else keeps there, and created exclusively by the caller."""
    return path.with_name(f".{path.name}.{secrets.token_hex(6)}.addystack-tmp")


def _remove(partial: Path) -> None:
    """Removes a partial from _beside that a failed write or link left; after a rename,
    nothing is there."""
    try:
        os.unlink(partial)
    except FileNotFoundError:
        pass


def _write(path: Path, text: str) -> None:
    """Writes text to path, through a link to the file it names; see _replace."""
    _replace(Path(os.path.realpath(path)), text)


def _replace(path: Path, text: str) -> None:
    """Replaces path with text by renaming a file written beside it, so a reader never sees
    half a file. A link at path is replaced, not written through. The new file keeps the
    mode of the file it replaces, so a private settings file stays private, plus the
    owner's read and write, so an unreadable file it replaces comes back readable; a new
    one gets the umask's. build writes through it too."""
    try:
        mode: Optional[int] = stat.S_IMODE(os.stat(path).st_mode) | stat.S_IRUSR | stat.S_IWUSR
    except OSError:
        mode = None
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = _beside(path)
    # Created private when it replaces a file, so its text is never readable by more than
    # the old file's was, then given that file's mode.
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if mode is not None else 0o666)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
            if mode is not None:
                os.fchmod(file.fileno(), mode)
        os.replace(partial, path)
    finally:
        _remove(partial)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _ledger() -> Dict[str, List[Tuple[str, str]]]:
    """The (event, command) pairs the last install wrote, by runtime; none when the ledger
    is missing or unreadable."""
    data = _read_json(LEDGER.expanduser())
    hooks = data.get("hooks") if isinstance(data, dict) else None
    found: Dict[str, List[Tuple[str, str]]] = {}
    for runtime, pairs in (hooks.items() if isinstance(hooks, dict) else ()):
        if isinstance(pairs, list):
            found[runtime] = [(pair[0], pair[1]) for pair in pairs
                              if isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) for p in pair)]
    return found


def _hooks(resolved: Resolved, runtime: hookset.Runtime, earlier: List[Tuple[str, str]],
           writes: Dict[Path, str]) -> Tuple[Optional[Change], List[List[str]]]:
    """The change to runtime's settings file, queued in writes, and the pairs it installs."""
    path = hookset.settings_path(runtime)
    enabled = bool(resolved["hosts"].get(runtime))
    if not enabled and not path.exists():
        return None, []
    try:
        document = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as error:
        raise ValueError(f"can't read {path}: {error}; fix it, then run addystack install") from error
    if not isinstance(document, dict):
        raise ValueError(f"{path} doesn't hold a JSON object; fix it, then run addystack install")
    entries = hookset.select(resolved, runtime) if enabled else []
    merged = hookset.merge(document, entries, hookset.owner(resolved, earlier, _moved_kits(resolved)))
    pairs = [[entry.event, entry.command] for entry in entries]
    if merged == document and path.exists():
        return None, pairs
    before = {(e["event"], e["command"]) for e in hookset._installed(document)}
    after = {(e["event"], e["command"]) for e in hookset._installed(merged)}
    lines = [f"+ {event} {command}" for event, command in sorted(after - before)]
    lines += [f"- {event} {command}" for event, command in sorted(before - after)]
    writes[path] = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    return Change("hooks", path, "\n".join(lines) or "regroups its hooks"), pairs


def _moved_kits(resolved: Resolved) -> List[str]:
    """The kit path the last build recorded in resolved.json, when it isn't this one: the
    checkout moved, as when a maintainer's kit moved into its own repo, so hooks rendered
    for that path are addystack's to re-point."""
    data = _read_json(_resolved.STATE.expanduser())
    earlier = data.get("kit") if isinstance(data, dict) else None
    if not isinstance(earlier, str) or os.path.realpath(os.path.expanduser(earlier)) == os.path.realpath(str(resolved["kit"])):
        return []
    return [earlier]


def _adopt(resolved: Resolved, writes: Dict[Path, str]) -> List[Change]:
    """Moves each enabled host's hand-written instruction file into the user's
    instructions file, queued in writes."""
    hosts = [(render.claude_md(), "claude"), (render.CODEX, "codex")]
    found = [(path.expanduser(), text) for path, host in hosts if resolved["hosts"].get(host)
             for text in [_hand_written(path.expanduser())] if text]
    if not found:
        return []
    target, named = _instructions_file()
    current = target.read_text() if target.is_file() else ""
    text = current
    moved = []
    for source, body in found:
        if body in text:
            continue
        if text.strip():
            heading = "" if _opens_with_heading(body) else f"# From {render._home(source)}\n\n"
            text = f"{text.rstrip()}\n\n{heading}{body}\n"
        else:
            text = f"{body}\n"
        moved.append(source)
    changes = []
    if text != current:
        writes[target] = text
        later = "; addystack init names it in your new config" if _user_layer() is None else ""
        changes.append(Change("adopt-instructions", target,
                              f"moves the text of {', '.join(render._home(path) for path in moved)} into it{later}"))
    if not named:
        changes += _name_instructions(writes)
    return changes


def _hand_written(path: Path) -> Optional[str]:
    """The file's text, stripped, when it holds text addystack didn't build; else None.
    Raises ValueError when it's there but can't be read or isn't UTF-8, since build would
    replace text nobody moved."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        reason = error.strerror if isinstance(error, OSError) else f"not UTF-8 text at byte {error.start}"
        raise ValueError(f"can't read {path}: {reason}; fix it or move it aside, then run addystack install") \
            from error
    if not text.strip() or text.lstrip().startswith(_BUILT):
        return None
    return text.strip()


def _opens_with_heading(text: str) -> bool:
    return text.startswith("# ")


def _user_layer() -> Optional[config.Layer]:
    return next((layer for layer in config.load_layers() if layer.name == "user"), None)


def _instructions_file() -> Tuple[Path, bool]:
    """The user's instructions file, and whether the config already names it."""
    layer = _user_layer()
    named = layer.data.get("instructions") if layer else None
    if isinstance(named, str):
        return Path(config._absolute(named, layer.dir)), True
    return config.CONFIG.expanduser().absolute().parent / _GLOBAL, False


def _name_instructions(writes: Dict[Path, str]) -> List[Change]:
    """Sets `"instructions": "global.md"` in the user's config, keeping its comments and
    layout; nothing without a config, since init names it."""
    path = config.CONFIG.expanduser().absolute()
    layer = _user_layer()
    if layer is None:
        return []
    text = path.read_text()
    value = _top_level_value(text, "instructions")
    if value is not None and text.startswith("null", value):
        edited: Optional[str] = f'{text[:value]}"{_GLOBAL}"{text[value + len("null"):]}'
    else:
        start = _opening_brace(text)
        if start is None:
            edited = None
        else:
            comma = "," if layer.data else ""
            edited = f'{text[:start + 1]}\n  "instructions": "{_GLOBAL}"{comma}{text[start + 1:]}'
    try:
        same = edited is not None and config._parse(path, edited) == {**layer.data, "instructions": _GLOBAL}
    except config.Invalid:
        same = False
    if not same:
        raise ValueError(f'couldn\'t add "instructions": "{_GLOBAL}" to {path}; add it yourself, then run '
                         "addystack install")
    writes[path] = edited
    return [Change("adopt-instructions", path, f'sets "instructions": "{_GLOBAL}", so the build carries it')]


def _skip(text: str, i: int) -> int:
    """The index of the next character past space and JSONC comments from i; an unclosed
    block comment runs to the end."""
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        else:
            break
    return i


def _string_end(text: str, i: int) -> int:
    """The index past the JSON string that opens at i."""
    end = i + 1
    while end < len(text) and text[end] != '"':
        end += 2 if text[end] == "\\" else 1
    return end + 1


def _top_level_value(text: str, key: str) -> Optional[int]:
    """The index where the value of the config's top-level `key` starts, or None. Text in
    comments and strings, and keys of nested objects, don't count."""
    depth, i = 0, 0
    while True:
        i = _skip(text, i)
        if i >= len(text):
            return None
        char = text[i]
        if char == '"':
            end = _string_end(text, i)
            colon = _skip(text, end)
            if depth == 1 and colon < len(text) and text[colon] == ":":
                try:
                    if json.loads(text[i:end]) == key:
                        return _skip(text, colon + 1)
                except ValueError:
                    return None
            i = end
        else:
            depth += 1 if char in "{[" else -1 if char in "}]" else 0
            i += 1


def _opening_brace(text: str) -> Optional[int]:
    """The index of the config's top-level `{`, past leading comments and space."""
    i = _skip(text, 0)
    return i if i < len(text) and text[i] == "{" else None

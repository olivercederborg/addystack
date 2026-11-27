"""Renders each host's instruction file from a Resolved config.

Takes over scripts/build-global.py's section merge. The router keeps three scalar
placeholders, `{{user}}`, `{{kit}}` for a path in prose, and `{{addystack}}` for the CLI as
a shell command word, quoted when the kit's path needs it, with no conditionals. Everything list-shaped
is a whole generated section: the repo policy table, the principles index without its
excluded principles, the reply rules, taste, and the user's `global.md`. Claude Code's
file imports the built parts with `@` lines, from ~/.local/state/addystack/; Codex's
file and ~/.agents/AGENTS.md, a tool-neutral file other agents' own instruction files
link to, have them inlined, since AGENTS.md has no imports.

The sources, all in the kit's core/ but the user's: `global.md` holds the team's
sections; `claude-code.md`, `codex.md`, and the tool-neutral `agents.md` add each host's preamble
and lines; each
Resolved `instructions` file follows, in layer order. Sections merge by `# ` heading in
that order: a heading's bodies join under its first appearance, and new headings follow.
A line that is only `@router.md` or `@principles.md` names a built part. `principles.md`
fills `{{taste}}` with the taste file's sentence, or nothing without one, and with
`judgment.principles.preset` `none` the part holds only the taste line, or goes, with its
import line, without a taste file. A path renders as
`~/…` when it's under $HOME. It renders no policy table or reply rules: the router runs
`addystack policy` per checkout, and a SessionStart hook loads the reply rules.

`ADDYSTACK_CLAUDE_MD`, `ADDYSTACK_CODEX_MD`, and `ADDYSTACK_AGENTS_MD` override claude_md(),
CODEX, and AGENTS, for tests and dry runs; resolved.STATE, which `ADDYSTACK_STATE` overrides, places the built parts.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import config
import hookset
import resolved as _resolved
from config import Resolved

CODEX = Path(os.environ.get("ADDYSTACK_CODEX_MD", "~/.codex/AGENTS.md"))
AGENTS = Path(os.environ.get("ADDYSTACK_AGENTS_MD", "~/.agents/AGENTS.md"))


def claude_md() -> Path:
    """Claude Code's user instructions file: CLAUDE.md in config.claude_home(), which is
    where Claude Code reads it, unless ADDYSTACK_CLAUDE_MD names another."""
    override = os.environ.get("ADDYSTACK_CLAUDE_MD")
    return Path(override).expanduser() if override else config.claude_home() / "CLAUDE.md"


_HEADER = ("<!-- Built by addystack build from the kit's core/ and your addystack config. Edit those and "
           "rerun addystack build. -->")
_PART = re.compile(r"^@(router|principles)\.md$", re.M)
_BULLET = re.compile(r"^- \*\*\[([\w-]+)\]\(")


def _home(path: Path) -> str:
    """path as `~/…` when it's under $HOME, or absolute."""
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


def _fill(text: str, values: Dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _fenced(lines: List[str]) -> List[bool]:
    """For each line, whether it's part of a code fence, its fence lines included, so a
    heading or an import line inside an example stays text."""
    flags, fence = [], None
    for line in lines:
        marker = _FENCE.match(line)
        if marker and fence is None:
            fence = marker.group(1)
            flags.append(True)
        elif fence is not None:
            flags.append(True)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                    and not line.strip()[len(marker.group(1)):]:
                fence = None
        else:
            flags.append(False)
    return flags


def _sections(text: str) -> Tuple[str, Dict[str, str]]:
    """Splits Markdown at each `# ` heading outside a code fence into
    (preamble, {heading: body})."""
    preamble: List[str] = []
    parts: Dict[str, List[str]] = {}
    current = None
    lines = text.split("\n")
    for line, fenced in zip(lines, _fenced(lines)):
        if not fenced and line.startswith("# "):
            current = parts.setdefault(line, [])
        else:
            (preamble if current is None else current).append(line)
    return "\n".join(preamble).strip(), {heading: "\n".join(body).strip() for heading, body in parts.items()}


def _merge(sources: List[str]) -> str:
    """The sources' preambles, then their sections merged by heading, in source order."""
    preambles: List[str] = []
    merged: Dict[str, List[str]] = {}
    for source in sources:
        preamble, sections = _sections(source)
        if preamble:
            preambles.append(preamble)
        for heading, body in sections.items():
            merged.setdefault(heading, []).extend([body] if body else [])
    blocks = preambles + [f"{heading}\n\n{chr(10).join(bodies)}" if bodies else heading
                          for heading, bodies in merged.items()]
    return "\n\n".join(blocks) + "\n"


def _expand(text: str, parts: Dict[str, str], link: Callable[[str], str]) -> str:
    """text with each built part's `@name.md` line outside a code fence replaced by
    link(name), or dropped, with its blank line, when the part isn't built."""
    lines = text.split("\n")
    out: List[str] = []
    dropped = False
    for line, fenced in zip(lines, _fenced(lines)):
        if dropped and not line:
            dropped = False
            continue
        dropped = False
        if not fenced and _PART.fullmatch(line):
            name = line[1:]
            if name in parts:
                out.append(link(name))
            else:
                dropped = True
            continue
        out.append(line)
    return "\n".join(out)


def _principles(resolved: Resolved, core: Path, values: Dict[str, str]) -> str:
    """The principles index without its excluded principles, with the taste sentence."""
    exclude = set(resolved["judgment"]["principles"]["exclude"])
    lines = [line for line in (core / "principles.md").read_text().split("\n")
             if not (_BULLET.match(line) and _BULLET.match(line).group(1) in exclude)]
    taste = resolved["judgment"]["taste"]
    sentence = f" What good code and UI look like:\n`{_home(Path(taste))}`." if taste else ""
    return _fill("\n".join(lines), {**values, "taste": sentence})


def placeholders(resolved: Resolved, kit: str = "") -> Dict[str, str]:
    """The router's placeholders for resolved, with {{kit}} as `kit`, by default the
    Resolved kit path."""
    return {"user": resolved["identity"]["name"], "kit": kit or _home(Path(resolved["kit"])),
            "addystack": f"{hookset._kit(resolved)}/bin/addystack"}


def built_parts(resolved: Resolved, core: Path, values: Dict[str, str]) -> Dict[str, str]:
    """The built parts from core/'s router.md and principles.md, by name, before their
    `@` lines are expanded: router.md, and principles.md unless resolved builds none."""
    parts = {"router.md": _fill((core / "router.md").read_text(), values)}
    if resolved["judgment"]["principles"]["preset"] != "none":
        parts["principles.md"] = _principles(resolved, core, values)
    elif resolved["judgment"]["taste"]:
        # Without the principles index, the taste file still gets its line.
        parts["principles.md"] = f"# Taste\n\nWhat good code and UI look like: `{_home(Path(resolved['judgment']['taste']))}`.\n"
    return parts


def outputs(resolved: Resolved) -> Dict[str, Path]:
    """Each enabled host's instruction file, by host."""
    paths = {"claude": claude_md(), "codex": CODEX.expanduser(), "agents": AGENTS.expanduser()}
    return {host: path for host, path in paths.items() if resolved["hosts"].get(host)}


def _hops(path: str) -> List[str]:
    """path, then each link it passes through to its file."""
    hops = [path]
    while os.path.islink(hops[-1]) and len(hops) < 40:
        hops.append(os.path.join(os.path.dirname(hops[-1]), os.readlink(hops[-1])))
    return hops


def _same_entry(a: str, b: str) -> bool:
    """Whether a and b name one folder entry, the one build replaces: the same folder,
    however spelled (or the same resolved path, for one not made yet), and the same name, or one cased differently on a disk that treats
    them as one. A hard link elsewhere is another entry, and build leaves it."""
    folder_a, folder_b = os.path.dirname(a) or ".", os.path.dirname(b) or "."
    both = os.path.isdir(folder_a) and os.path.isdir(folder_b)
    if not (os.path.samefile(folder_a, folder_b) if both else os.path.realpath(folder_a) == os.path.realpath(folder_b)):
        return False
    name_a, name_b = os.path.basename(a), os.path.basename(b)
    return name_a == name_b or (name_a.casefold() == name_b.casefold() and os.path.lexists(a)
                                and os.path.lexists(b) and os.path.samestat(os.lstat(a), os.lstat(b)))


def aliases(resolved: Resolved) -> List[config.Issue]:
    """An issue for each instructions file that reaches a file build writes, itself or
    through links, since build would overwrite the source with its own output, and for
    two hosts that write one file, since each build would undo the other. A host file
    that links to the source is fine: build replaces the link."""
    built = [(host, str(path)) for host, path in outputs(resolved).items()]
    issues = [config.Issue("instructions", f"{_home(Path(source))} is the file build writes for hosts.{host}; "
                                           "keep your instructions in another file")
              for source in resolved["instructions"]
              for host in sorted({host for hop in _hops(source) for host, path in built if _same_entry(hop, path)})]
    return issues + [config.Issue("hosts", f"hosts.{first} and hosts.{second} both write {_home(Path(path))}; "
                                           "turn one off")
                     for index, (first, path) in enumerate(built) for second, other in built[index + 1:]
                     if _same_entry(path, other)]


def instructions(resolved: Resolved) -> Dict[Path, str]:
    """Each file to write, by absolute path: the hosts' instruction files and the built
    parts the Claude file imports."""
    core = Path(resolved["kit"]) / "core"
    values = placeholders(resolved)
    parts = built_parts(resolved, core, values)
    mine = [config.read_text(Path(path)) for path in resolved["instructions"]]
    state = _resolved.STATE.expanduser().parent
    files: Dict[Path, str] = {}

    def body(host: str) -> str:
        return _merge([_fill((core / name).read_text(), values) for name in ("global.md", host)] + mine)

    hosts = outputs(resolved)
    if "claude" in hosts:
        def imported(name: str) -> str:
            return f"@{_home(state / name)}"

        files[hosts["claude"]] = f"{_HEADER}\n{_expand(body('claude-code.md'), parts, imported)}"
        for name, text in parts.items():
            files[state / name] = _expand(text, parts, imported)
    def inlined(name: str) -> str:
        return _expand(parts[name], parts, inlined).rstrip("\n")

    for host, template in (("codex", "codex.md"), ("agents", "agents.md")):
        if host in hosts:
            files[hosts[host]] = f"{_HEADER}\n{_expand(body(template), parts, inlined)}"
    return files

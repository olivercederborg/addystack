"""Checks an addystack install, one line per check.

The checks: the config against schema/v1.json; the built files are fresh (`build
--check`); each note names a core skill that hasn't changed since the note was built
(notes.problems); `claude` and `codex` on PATH with their versions, for each host the config
enables; in each enabled host's skill folder, no skill the release lists (core/skills.json)
is a dangling link and each installed core skill has its SKILL.md, from an `npx skills
add` install or a link into a maintainer's checkout, while a core skill that isn't
installed is a note, since a user may install some with `--skill` and update leaves a
removed one removed; with the claude host enabled and verify-work in its skill folder,
agents/work-verifier.md in Claude Code's folder is the work-verifier agent, as install links
it (reconcile.agent()), or a file holding verify-work's copy's text; the installed hooks match the selection
(hookset.drift); and the tools the policy needs, `gh` and `gh stack` when the defaults or
a repo rule push through gh stack, are present.

A check skipped because the config didn't resolve reports `skipped: …`, with ok True,
since the config check fails.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import config
import hookset
import notes
import reconcile
import render
import resolved as _resolved
import skill_layer
import skills_cli
from config import Resolved

_SKIPPED = "skipped: the config didn't resolve"
# Seconds to wait for a tool's --version or --help.
_TIMEOUT = 10


@dataclass(frozen=True)
class Check:
    """One check's result, with the command or edit that fixes it when it fails."""
    name: str
    ok: bool
    detail: str
    fix: Optional[str]


def _config(value: Optional[Resolved]) -> Check:
    fix = f"edit {config.CONFIG}, then run addystack doctor"
    if value is not None:
        return Check("config", True, f"valid, layers {', '.join(value['layers'])}", None)
    try:
        issues = config.validate(config.load_layers())
    except config.Invalid as invalid:
        issues = invalid.issues
    return Check("config", False, "; ".join(f"{issue.path}: {issue.message}" for issue in issues), fix)


def _read(path: Path) -> Optional[str]:
    """path's text, or None for a link or a file that's missing or can't be read."""
    try:
        return None if path.is_symlink() or not path.is_file() else path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _stale(value: Resolved) -> Dict[Path, Optional[str]]:
    """Each file `addystack build` writes whose current text isn't the built text, with
    that text, and each built note it removes, with None. build, build --check, and doctor
    all decide freshness here."""
    outputs = {_resolved.STATE.expanduser(): json.dumps(value, indent=2) + "\n", **render.instructions(value),
               **notes.built(value)}
    return {**{path: text for path, text in outputs.items() if _read(path) != text},
            **{path: None for path in notes.orphans(value)}}


def _fresh(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("built files", True, _SKIPPED, None)
    stale = _stale(value)
    if stale:
        return Check("built files", False, f"out of date: {', '.join(map(str, stale))}", "addystack build")
    return Check("built files", True, "match the config", None)


def _notes(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("notes", True, _SKIPPED, None)
    found = notes.problems(value)
    if found:
        return Check("notes", False, "; ".join(problem for problem, _ in found), "; ".join(fix for _, fix in found))
    names = [note.stem for note in notes.sources()]
    return Check("notes", True, ", ".join(names) if names else f"none in {notes.source_dir()}", None)


def _enabled(value: Resolved) -> List[str]:
    return [host for host in ("claude", "codex") if value["hosts"].get(host)]


def _output(argv: List[str]) -> Optional[str]:
    """The command's first output line when it exits 0, else None."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (done.stdout or done.stderr).strip().splitlines()
    return (lines[0] if lines else "") if done.returncode == 0 else None


def _hosts(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("hosts", True, _SKIPPED, None)
    found, missing = [], []
    for host in _enabled(value):
        path = shutil.which(host)
        version = _output([path, "--version"]) if path else None
        if version is None:
            missing.append(host)
        else:
            found.append(f"{host} {version}".strip())
    if missing:
        names = " and ".join(missing)
        return Check("hosts", False, f"{names} {'is' if len(missing) == 1 else 'are'} enabled but not on PATH, or "
                     "--version fails", f"install {names}, or set {', '.join(f'hosts.{h}' for h in missing)} to false "
                     f"in {config.CONFIG}")
    return Check("hosts", True, ", ".join(found) or "none enabled", None)


def _skill_links(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("skill links", True, _SKIPPED, None)
    kit = Path(value["kit"])
    release = skill_layer.released(kit)
    if release is None:
        return Check("skill links", False, f"{kit / skill_layer.RELEASE} is missing or unreadable",
                     "reinstall addystack with npx skills add")
    core = skill_layer.core(release)
    source = skills_cli.add_source(skills_cli.locked()) or "<the addystack repo>"
    problems, notes, missing = [], [], set()
    for host in _enabled(value):
        folder = skills_cli.folder(host)
        dangling = [name for name in release if (folder / name).is_symlink() and not (folder / name).exists()]
        # Installed, as a folder or a link that resolves, without its SKILL.md.
        broken = [name for name in core if (folder / name).exists() and not (folder / name / "SKILL.md").is_file()]
        absent = [name for name in core if not os.path.lexists(folder / name)]
        missing.update(broken + [name for name in dangling if name in core])
        problems += [f"{render._home(folder / name)} is a dangling link" for name in dangling]
        problems += [f"{render._home(folder / name)} has no SKILL.md" for name in broken]
        if absent:
            notes.append(f"{render._home(folder)} has {len(core) - len(absent)} of {len(core)} core skills; not "
                         f"installed: {', '.join(absent)} (npx skills add {source} -g -y --skill {' '.join(absent)} "
                         "adds them)")
    if not problems:
        return Check("skill links", True,
                     "; ".join(notes) or f"{len(core)} core skills in each enabled host's folder", None)
    fix = "remove each dangling link, then " if any("dangling" in problem for problem in problems) else ""
    names = " ".join(sorted(missing)) or "<each dangling skill>"
    return Check("skill links", False, "; ".join(problems),
                 f"{fix}run npx skills add {source} -g -y --skill {names}, or link each from your checkout")


def _is_verifier(path: Path) -> bool:
    """Whether path reads as an agent whose frontmatter names it work-verifier."""
    try:
        lines = path.read_text().split("\n")
    except (OSError, UnicodeDecodeError):
        return False
    if lines[0] != "---" or "---" not in lines[1:]:
        return False
    return any(re.fullmatch(r"name:\s*(['\"]?)work-verifier\1\s*", line) for line in lines[1:lines.index("---", 1)])


def _same_text(path: Path, other: Path) -> bool:
    """Whether path and other both read and hold the same bytes."""
    try:
        return path.read_bytes() == other.read_bytes()
    except OSError:
        return False


def _agent(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("agent", True, _SKIPPED, None)
    if not value["hosts"].get("claude"):
        return Check("agent", True, "not needed: the claude host is off", None)
    link, source = reconcile.agent(), reconcile.agent_source()
    regular = os.path.lexists(link) and not link.is_symlink()
    # A link counts only when it's install's, to the copy verify-work ships: one to an older
    # copy, such as a kit checkout's repo root, would run that copy's instructions. A file
    # counts only when it holds that copy's text, for the same reason.
    if _is_verifier(link) and (_same_text(link, source) if regular else os.readlink(link) == str(source)):
        return Check("agent", True, f"{render._home(link)} is the work-verifier agent"
                     + ("" if regular else f", through {render._home(source)}"), None)
    if not os.path.lexists(source.parents[1]):
        return Check("agent", True, f"not needed: verify-work isn't in {render._home(source.parents[2])}", None)
    # verify-work's own copy is missing, or there but not the agent: only reinstalling
    # verify-work restores it, since install links to it as it is.
    restore = not _is_verifier(source)
    install = "addystack install"
    if restore:
        kit = skills_cli.add_source(skills_cli.locked()) or "<the addystack repo>"
        install = f"npx skills add {kit} -g -y --skill verify-work, then addystack install"
    fix = f"run {install}" if restore else install
    if regular:
        if not _is_verifier(link):
            problem = f"{render._home(link)} isn't the work-verifier agent"
        elif source.is_file():
            problem = f"{render._home(link)} differs from {render._home(source)}, so it's an older or edited copy"
        else:
            problem = (f"{render._home(link)} is a copy of the work-verifier agent, and {render._home(source)} "
                       "is missing")
        fix = f"move {render._home(link)} aside, then run {install}"
    elif not link.is_symlink():
        problem = f"{render._home(link)} is missing"
    elif os.readlink(link) == str(source):
        problem = (f"{render._home(link)} links to {render._home(source)}, which "
                   + ("isn't the work-verifier agent" if source.is_file() else "is missing"))
    else:
        problem = f"{render._home(link)} links to {os.readlink(link)}, not {render._home(source)}"
    return Check("agent", False, f"{problem}; verify-work's fork needs it to record a Done verdict", fix)


def _hooks(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("hooks", True, _SKIPPED, None)
    lines = [line for host in _enabled(value) for line in hookset.drift(value, host)]
    # Codex skips a hook it doesn't trust, and trust follows a hook's position, so removing
    # an entry above a gate untrusts the gate until the user trusts it again.
    trust = []
    if "codex" in _enabled(value) and shutil.which("codex"):
        import hook_parity
        trust = [line for line in hook_parity._codex_trust()
                 if "not checked" not in line and "lists no hooks" not in line]
    if lines or trust:
        fix = " and ".join(step for step, needed in (("addystack install", lines),
                                                     ("trust each in codex's /hooks", trust)) if needed)
        return Check("hooks", False, "; ".join(lines + trust), fix)
    return Check("hooks", True, "match the selection" if _enabled(value) else "no host enabled", None)


def _policy_tools(value: Optional[Resolved]) -> Check:
    if value is None:
        return Check("policy tools", True, _SKIPPED, None)
    table = value["policy"]
    if all(fields.get("pushVia") != "gh-stack" for fields in [table["defaults"], *(r["set"] for r in table["rules"])]):
        return Check("policy tools", True, "none needed", None)
    gh = shutil.which("gh")
    if gh is None:
        return Check("policy tools", False, "gh isn't on PATH, and a rule pushes through gh stack",
                     "install the GitHub CLI (https://cli.github.com), then gh extension install github/gh-stack")
    if _output([gh, "stack", "--help"]) is None:
        return Check("policy tools", False, "gh stack isn't installed, and a rule pushes through gh stack",
                     "gh extension install github/gh-stack")
    return Check("policy tools", True, "gh and gh stack", None)


def run(resolved: Optional[Resolved]) -> List[Check]:
    """Every check. With resolved None, the config didn't resolve, so the config check
    fails with its issues and the checks that need a resolved config are skipped."""
    return [_config(resolved), _fresh(resolved), _notes(resolved), _hosts(resolved), _skill_links(resolved),
            _agent(resolved), _hooks(resolved), _policy_tools(resolved)]

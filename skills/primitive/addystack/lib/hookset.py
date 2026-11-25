"""Selects, renders, and compares the hooks a Resolved config installs.

Takes over hooks/render_hooks.py and hooks/hook_parity.py, which stay as thin wrappers
until M3. Each hooks/manifest.json entry has an `id`, `tags` (`safety`, `workflow`,
`replies`, `machine`, or `trial`, which no preset includes), an optional `requires` (a dotted Resolved path that must be truthy,
such as `replies.rules`, or `path=value` for one that must equal a string, such as
`replies.style=reply-shape`), and a `{{kit}}` prefix on its command. Selection runs in
this order and keeps manifest order, since Codex trusts a hook by its position:

1. the hook preset's tags: `recommended` is safety and workflow, `all` adds replies and
   machine;
2. `requires`, which an explicit enable can't bypass;
3. `hooks.enable` and `hooks.disable`, by id;
4. the entry's `hosts`.

`{{kit}}` becomes the Resolved kit path, as `~/…` when it's under $HOME, the way the
committed host settings write it. A host is a profile: `darwin`, `linux`, or `sandbox`
(a Linux host, so `linux` entries apply there too), and `auto` picks this machine's.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Tuple

import config
from config import Resolved

Runtime = Literal["claude", "codex"]

MANIFEST = Path(__file__).resolve().parent.parent / "hooks" / "manifest.json"
RUNTIMES: Tuple[Runtime, ...] = ("claude", "codex")
PRESETS = {"recommended": {"safety", "workflow"}, "all": {"safety", "workflow", "replies", "machine"}}
PROFILES = {"darwin": {"darwin"}, "linux": {"linux"}, "sandbox": {"linux", "sandbox"}}
_FIELDS = ("matcher", "timeout", "onFailure")
# Hook scripts the kit once installed and has since deleted. A checkout that fast-forwards
# past the deletion still has the command in its settings until the next install, so a
# command on one is addystack's wherever a manifest script's would be: in this kit's hooks
# folder, an earlier kit's, or an older install's link folder. Drift reports it as extra,
# and an install removes it, with or without a ledger entry. reply-card.py went with
# reply-shape's UI cards (Nov 2026), and the rest with r165's cut to the hooks that guard
# hard-to-undo steps (Nov 18, 2026).
RETIRED = ("reply-card.py", "bash-rewrite.py", "no-foreground-waits.py", "ssh-signing-blocked.py",
           "unparsed-bash-rewrite.py", "bug-route.py", "coordinator-light.py", "existing_work.py",
           "gh-stack-only.py", "require-writing-for-agents.py", "t3-children-only.py",
           "thread-titles.py", "bare_references.py", "coordinator_queue.py", "pr_watch.py",
           "reply_budget.py", "routine_stop.py", "upload_handoff.py")


@dataclass(frozen=True)
class HookEntry:
    """One selected hook, with its command's `{{kit}}` filled in."""
    id: str
    event: str
    matcher: Optional[str]
    command: str
    timeout: int
    onFailure: Optional[str]


def settings_path(runtime: Runtime) -> Path:
    """The settings file runtime reads its hooks from: Claude Code's settings.json in
    config.claude_home(), or Codex's ~/.codex/hooks.json."""
    if runtime == "claude":
        return config.claude_home() / "settings.json"
    return Path("~/.codex/hooks.json").expanduser()


def host_profile(name: str = "auto") -> str:
    """The profile name names, or for auto this machine's: darwin, linux, or sandbox."""
    if name != "auto":
        if name not in PROFILES:
            raise ValueError(f"unknown profile {name!r}; use one of auto, {', '.join(PROFILES)}")
        return name
    if os.environ.get("SBX_SANDBOX") == "1":
        return "sandbox"
    return "darwin" if sys.platform == "darwin" else "linux"


def applies(entry: Dict[str, Any], profile: str) -> bool:
    """True when a manifest entry applies on profile: it has no `hosts`, or they name it."""
    return not entry.get("hosts") or bool(PROFILES[profile] & set(entry["hosts"]))


def select(resolved: Resolved, runtime: Runtime, host: str = "auto") -> List[HookEntry]:
    """The hooks to install for runtime on this host, in manifest order."""
    return _select(_manifest(MANIFEST)[runtime], resolved, host)


def render(entries: List[HookEntry]) -> Dict[str, Any]:
    """The host settings' `hooks` value for entries, grouped by event and matcher.

    Each event's hooks come in entries' order, consecutive entries with the same matcher
    share a group, and events come in the order entries first name them."""
    hooks: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        groups = hooks.setdefault(entry.event, [])
        matcher = entry.matcher or None
        group = groups[-1] if groups and groups[-1].get("matcher") == matcher else None
        if group is None:
            group = {**({"matcher": matcher} if matcher else {}), "hooks": []}
            groups.append(group)
        group["hooks"].append({"type": "command", "command": entry.command, "timeout": entry.timeout,
                               **({"onFailure": entry.onFailure} if entry.onFailure else {})})
    return hooks


def merge(document: Dict[str, Any], entries: List[HookEntry], owned: Callable[[str, str], bool]) -> Dict[str, Any]:
    """A host settings document with entries' hooks in its `hooks` key, keeping every other
    key and every hook addystack didn't install, in order.

    owned(event, command) says which installed hooks are addystack's: each is removed, and a
    group left empty goes. Each event's selected groups take the place of its first removed
    hook, so a hook keeps its position across installs, since Codex trusts by position; an
    event with none removed gets them after its other groups."""
    rendered = render(entries)
    current = document.get("hooks")
    merged: Dict[str, Any] = {}
    for event, groups in (current.items() if isinstance(current, dict) else ()):
        if not isinstance(groups, list):
            merged[event] = groups
            continue
        kept: List[Any] = []
        place: Optional[int] = None
        for group in groups:
            hooks = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(hooks, list):
                kept.append(group)
                continue
            theirs = [hook for hook in hooks if not (isinstance(hook, dict) and isinstance(hook.get("command"), str)
                                                     and owned(event, hook["command"]))]
            if len(theirs) != len(hooks) and place is None:
                place = len(kept)
            if theirs:
                kept.append({**group, "hooks": theirs})
        ours = rendered.pop(event, [])
        at = len(kept) if place is None else place
        kept[at:at] = ours
        if kept:
            merged[event] = kept
    merged.update(rendered)
    if not merged and "hooks" not in document:
        return dict(document)
    return {**document, "hooks": merged}


def owner(resolved: Resolved, earlier: Iterable[Tuple[str, str]] = (),
          moved: Iterable[str] = ()) -> Callable[[str, str], bool]:
    """owned(event, command) for merge(): True for a hook addystack installed, which is one in
    earlier, the (event, command) pairs an install recorded, or one a manifest entry renders
    for this kit or an older install's link to a manifest script runs (see _ours), or one
    that runs a manifest script in the hooks folder of a kit in moved, the paths the kit
    was built from before, so moving the kit's checkout re-points its hooks instead of
    adding a second copy. Any other hook on a script in the kit's hooks folder is the user's."""
    manifest = _manifest(MANIFEST)
    recorded = set(earlier)
    folders = {os.path.join(os.path.expanduser(kit), "hooks") for kit in moved}
    return lambda event, command: ((event, command) in recorded or _ours(command, manifest, _kit(resolved))
                                   or _moved(command, manifest, folders))


def drift(resolved: Resolved, runtime: Runtime, path: Optional[Path] = None) -> List[str]:
    """One line per difference between the selected hooks and the addystack hooks the
    host's settings file holds. Hooks addystack didn't install aren't compared."""
    return _drift(_manifest(MANIFEST), resolved, runtime, path, required=True, host="auto")


def _manifest(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    return json.loads(Path(path).read_text())


def _truthy(resolved: Resolved, dotted: Optional[str]) -> bool:
    """Whether the Resolved value at a dotted path is truthy, or with `path=value`, equals
    that string; a missing key is neither."""
    if dotted is None:
        return True
    dotted, equals, wanted = dotted.partition("=")
    value: Any = resolved
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return value == wanted if equals else bool(value)


def _kit(resolved: Resolved) -> str:
    """The Resolved kit path as a command prefix: `~/…` under $HOME, else absolute, quoted
    for the shell when it needs it."""
    kit = str(resolved["kit"])
    if shlex.quote(kit) != kit:
        # A quoted `~` isn't expanded, so a path that needs quotes stays absolute.
        return shlex.quote(kit)
    try:
        return f"~/{Path(kit).relative_to(Path.home())}"
    except ValueError:
        return kit


def _chosen(entry: Dict[str, Any], resolved: Resolved) -> bool:
    """Steps 1 to 3 of selection: preset tags, requires, then enable and disable by id."""
    hooks = resolved["hooks"]
    if not _truthy(resolved, entry.get("requires")):
        return False
    if entry["id"] in hooks["disable"]:
        return False
    return bool(PRESETS[hooks["preset"]] & set(entry["tags"])) or entry["id"] in hooks["enable"]


def _entry(entry: Dict[str, Any], kit: str) -> HookEntry:
    return HookEntry(id=entry["id"], event=entry["event"], matcher=entry.get("matcher") or None,
                     command=entry["command"].replace("{{kit}}", kit), timeout=entry["timeout"],
                     onFailure=entry.get("onFailure"))


def _select(entries: Iterable[Dict[str, Any]], resolved: Resolved, host: str = "auto") -> List[HookEntry]:
    """select() over a runtime's manifest entries."""
    profile, kit = host_profile(host), _kit(resolved)
    return [_entry(entry, kit) for entry in entries if _chosen(entry, resolved) and applies(entry, profile)]


def _installed(config: Any) -> List[Dict[str, Any]]:
    """The flat hook entries of a settings.json or hooks.json `hooks` object."""
    hooks = config.get("hooks") if isinstance(config, dict) else None
    entries = []
    for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
        for group in (groups if isinstance(groups, list) else ()):
            if not isinstance(group, dict):
                continue
            for hook in (group.get("hooks") if isinstance(group.get("hooks"), list) else ()):
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    entries.append({"event": event, "matcher": group.get("matcher") or None,
                                    "command": hook["command"], "timeout": hook.get("timeout"),
                                    "onFailure": hook.get("onFailure")})
    return entries


def _script(command: str) -> str:
    """The command's script, `~` expanded."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return os.path.expanduser(words[0]) if words else ""


def _legacy_dirs() -> Tuple[str, ...]:
    """Where installs before addystack linked the kit's hook scripts: the hooks folder in
    Claude Code's folder, in ~/.claude too, since a settings file copied into a new
    CLAUDE_CONFIG_DIR still runs the old links, and in ~/.codex."""
    folders = (str(config.claude_home() / "hooks"), os.path.expanduser("~/.claude/hooks"),
               os.path.expanduser("~/.codex/hooks"))
    return tuple(dict.fromkeys(folders))


def _words(command: str) -> Tuple[str, ...]:
    """The command's words with its script's `~` expanded, so `~/kit/x.py` and its
    absolute form compare equal."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return (os.path.expanduser(words[0]), *words[1:]) if words else ()


def _ours(command: str, manifest: Dict[str, List[Dict[str, Any]]], kit: str) -> bool:
    """Whether addystack installed this command, for an install with no ledger entry for it:
    it's a manifest entry's command as rendered for this kit, any runtime's, or it runs an
    older install's link (a symlink or a missing path, never a regular file) in _legacy_dirs()
    whose name, or whose target's name, is a script the manifest runs. A user's own hook on
    another script in the kit's hooks folder isn't, nor one elsewhere that shares a name,
    such as /opt/my-hooks/merge-gate.py. A RETIRED script in this kit's hooks folder is."""
    words = _words(command)
    if any(words == _words(_entry(entry, kit).command) for rows in manifest.values() for entry in rows):
        return True
    script = _script(command)
    folder = os.path.dirname(script)
    # As _script reads the rendered command, since a kit path with a space is quoted.
    if script in {_script(f"{kit}/hooks/{name}") for name in RETIRED}:
        return True
    scripts = _scripts(manifest)
    if folder not in {os.path.expanduser(legacy) for legacy in _legacy_dirs()}:
        return False
    # A link, or a leftover entry whose link is gone. A regular file there is the user's
    # own hook, whatever its name.
    if os.path.lexists(script) and not os.path.islink(script):
        return False
    return os.path.basename(script) in scripts or os.path.basename(os.path.realpath(script)) in scripts


def _scripts(manifest: Dict[str, List[Dict[str, Any]]]) -> set:
    """The names of the scripts addystack installs, or once did: the manifest's and RETIRED."""
    return {os.path.basename(_script(entry["command"])) for rows in manifest.values() for entry in rows} | set(RETIRED)


def _moved(command: str, manifest: Dict[str, List[Dict[str, Any]]], folders: Iterable[str]) -> bool:
    """Whether command runs a script the manifest runs, or a RETIRED one, from one of
    folders, an earlier kit's hooks folder."""
    script = _script(command)
    return os.path.dirname(script) in set(folders) and os.path.basename(script) in _scripts(manifest)


def _drift(manifest: Dict[str, List[Dict[str, Any]]], resolved: Resolved, runtime: Runtime,
           path: Optional[Path], required: bool, host: str) -> List[str]:
    """drift() over a manifest, for a host profile. A missing file is drift only when
    required. A hook the manifest declares for other hosts only isn't drift when present."""
    profile = host_profile(host)
    path = Path(path).expanduser() if path else settings_path(runtime)
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        return [f"{runtime}: {path} is missing"] if required else []
    except (OSError, ValueError) as error:
        return [f"{runtime}: can't read {path}: {error}"]
    kit = _kit(resolved)
    entries = manifest[runtime]
    wanted = [_entry(entry, kit) for entry in entries if _chosen(entry, resolved) and applies(entry, profile)]
    elsewhere = {(e.event, e.command) for e in (_entry(entry, kit) for entry in entries
                                                if _chosen(entry, resolved) and not applies(entry, profile))}
    installed = [e for e in _installed(config) if _ours(e["command"], manifest, kit)]
    unmatched = list(installed)
    matched = []  # (selected entry, installed entry), in manifest order
    lines = []
    for want in wanted:
        have = next((e for e in unmatched if (e["event"], e["command"]) == (want.event, want.command)), None)
        if have is None:
            lines.append(f"{runtime}: missing {want.event} {want.command}")
            continue
        unmatched.remove(have)
        matched.append((want, have))
        for field in _FIELDS:
            if have[field] != getattr(want, field):
                lines.append(f"{runtime}: {want.event} {want.command} has {field} "
                             f"{json.dumps(have[field])}, manifest says {json.dumps(getattr(want, field))}")
        script = _script(want.command)
        if not os.path.exists(script):
            lines.append(f"{runtime}: {want.event} {want.command}: {script} doesn't exist")
    lines += [f"{runtime}: extra {e['event']} {e['command']}" for e in unmatched
              if (e["event"], e["command"]) not in elsewhere]
    for event in dict.fromkeys(want.event for want, _ in matched):
        want_order = [w.command for w, _ in matched if w.event == event]
        have_order = [e["command"] for e in installed if any(e is h for w, h in matched if w.event == event)]
        if have_order != want_order:
            lines.append(f"{runtime}: {event} runs {_names(have_order)}; manifest order is {_names(want_order)}")
    return lines


def _names(commands: List[str]) -> str:
    return ", ".join(" ".join([Path(c.split()[0]).name, *c.split()[1:]]) for c in commands)

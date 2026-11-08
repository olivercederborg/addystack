#!/usr/bin/env python3
"""Checks each machine's installed hooks against the declared set: the manifest.json
entries lib/hookset.py selects for the built addystack config. Added after a second machine's
~/.claude/settings.json sat a week stale, 5 hooks short, and its Codex had no hooks.json
at all, and nothing noticed (Oct 2026).

    python3 hooks/hook_parity.py [--claude PATH] [--codex PATH] [--codex-trust]
                                 [--profile auto|darwin|linux|sandbox]

prints one line per drift and exits 1 on any. A missing Codex hooks.json is drift only
when `codex` is on PATH or --codex was passed. --codex-trust also asks `codex app-server`
which hooks it trusts: Codex skips an untrusted hook entirely.

A thin wrapper over hookset until M3. The declared set comes from the built resolved.json
(resolved.STATE, which ADDYSTACK_STATE overrides), or from the kit's defaults alone when
it's missing or can't be read, so a machine without a build expects the `recommended`
hooks. Only hooks addystack installs are compared: a manifest entry's command as rendered for
the kit, or an older install's link to a manifest script (hookset._ours).

Order counts: Codex trusts a hook by its position, so a declared hook in another place
within its event is drift too.

A manifest entry with `hosts` applies only on those host profiles. On another profile
it's neither required nor drift when present. --profile auto, the default, is darwin
on macOS, linux elsewhere, and sandbox when SBX_SANDBOX=1. A sandbox is a Linux host,
so linux entries apply there too."""
import argparse, contextlib, json, os, pathlib, queue, shutil, subprocess, sys, threading

HOOKS = pathlib.Path(__file__).resolve().parent
# First on the path, so a project's own config.py or hookset.py on PYTHONPATH can't stand
# in for the kit's.
sys.path[:0] = [str(HOOKS), str(HOOKS.parent / "lib")]
import config  # noqa: E402
import hookset  # noqa: E402
import resolved  # noqa: E402
from hookset import PROFILES, RUNTIMES, applies, host_profile  # noqa: E402,F401

MANIFEST = HOOKS / "manifest.json"


def __getattr__(name):
    """PATHS, each runtime's settings file as ~/… under $HOME, as it read before Claude Code's
    followed CLAUDE_CONFIG_DIR, built on each read. The workshop's env_fingerprint reads it."""
    if name == "PATHS":
        home = pathlib.Path.home()
        paths = {runtime: hookset.settings_path(runtime) for runtime in RUNTIMES}
        return {runtime: f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
                for runtime, path in paths.items()}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
TRUST_TIMEOUT = 20  # seconds to wait for each codex app-server reply


def resolved_config():
    """The Resolved the declared set comes from: the built resolved.json as resolved.py
    validates it, or the kit's defaults alone when it's missing, unreadable, or has a
    field resolved.py or selection reads that's absent or of the wrong type."""
    try:
        # resolved._state() falls back to the kit's defaults on its own fields, so replies
        # and kit can't be missing or null here.
        data = resolved._state()
        _check_selection_fields(data)
        for runtime in RUNTIMES:
            hookset._select([], data)
            for entry in json.loads(MANIFEST.read_text())[runtime]:
                hookset._chosen(entry, data)
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # A user config that can't exist, so only the kit's defaults load.
        return config.merge(config.load_layers(pathlib.Path(os.devnull) / "none"), HOOKS.parent)


def _check_selection_fields(data):
    """Raises ValueError unless the fields selection reads have the shapes it assumes: a
    string that isn't a list of ids would pass membership checks letter by letter, and
    an empty kit would render every command as `/hooks/…`."""
    hooks = data["hooks"]
    if hooks["preset"] not in hookset.PRESETS:
        raise ValueError(f"hooks.preset {hooks['preset']!r}")
    for key in ("enable", "disable"):
        if not isinstance(hooks[key], list) or not all(isinstance(i, str) for i in hooks[key]):
            raise ValueError(f"hooks.{key} isn't a list of ids")
    kit = data["kit"]
    if not isinstance(kit, str) or not os.path.isabs(kit):
        raise ValueError("kit isn't an absolute path")


def selected(runtime, profile="auto"):
    """The hookset entries for runtime on profile, from MANIFEST and resolved_config()."""
    return hookset._select(json.loads(MANIFEST.read_text())[runtime], resolved_config(), profile)


def declared(runtime, profile="auto"):
    """The selected entries for runtime that apply on profile, in manifest order, as
    manifest-shaped dicts with `{{kit}}` filled in."""
    return [{"id": e.id, "event": e.event, "matcher": e.matcher, "command": e.command, "timeout": e.timeout,
             **({"onFailure": e.onFailure} if e.onFailure else {})} for e in selected(runtime, profile)]


def drift(runtime, path=None, required=True, profile="auto"):
    """Drift lines for runtime ("claude" or "codex"): selected entries for profile missing
    from the config at path, addystack hooks the selection doesn't declare, a changed
    matcher, timeout, or onFailure, a command whose script doesn't exist, and an event
    whose declared hooks run in another order than the manifest's. An installed entry the
    manifest declares for other hosts only isn't drift. A missing file is drift only when
    required."""
    return hookset._drift(json.loads(MANIFEST.read_text()), resolved_config(), runtime, path, required, profile)


def _codex_trust():
    """Lines for each Codex hook whose trustStatus isn't trusted, from `codex app-server`."""
    codex = shutil.which("codex")
    if not codex:
        return ["codex trust: not checked, codex isn't on PATH"]
    try:
        server = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
    except OSError as error:
        return [f"codex trust: not checked, codex app-server didn't start: {error}"]
    replies = queue.Queue()

    def read():
        for line in server.stdout:
            replies.put(line)
        replies.put("null")

    threading.Thread(target=read, daemon=True).start()

    def send(message):
        try:
            server.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            server.stdin.flush()
        except BrokenPipeError:  # it exited before reading; closing drops the unsent line
            with contextlib.suppress(OSError):
                server.stdin.close()
            raise OSError("it exited") from None

    def reply(id_):
        while True:
            message = json.loads(replies.get(timeout=TRUST_TIMEOUT))
            if message is None:
                raise OSError("it exited")
            if message.get("id") == id_:
                return message

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "hook-parity", "version": "0"}}})
        reply(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "hooks/list", "params": {"cwds": ["/tmp"]}})
        result = reply(2)
    except (queue.Empty, OSError, ValueError) as error:
        return [f"codex trust: not checked, codex app-server didn't answer: {error or 'timed out'}"]
    finally:
        server.kill()
    if "error" in result:
        return [f"codex trust: not checked, hooks/list failed: {result['error']}"]
    data = result.get("result", {}).get("data", [])
    hooks = [hook for entry in data for hook in entry.get("hooks", [])]
    if not hooks:
        return ["codex trust: codex app-server lists no hooks"]
    return [f"codex trust: {error}" for entry in data for error in entry.get("errors", [])] + [
        f"codex trust: {hook.get('key')} is {hook.get('trustStatus')}: {hook.get('command')}"
        for hook in hooks if hook.get("trustStatus") != "trusted"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", help=f"default {hookset.settings_path('claude')}")
    parser.add_argument("--codex", help=f"default {hookset.settings_path('codex')}")
    parser.add_argument("--codex-trust", action="store_true",
                        help="also ask codex app-server which hooks it trusts")
    parser.add_argument("--profile", default="auto", choices=("auto", *PROFILES),
                        help="the host profile whose hooks to expect (default auto)")
    args = parser.parse_args()
    lines = drift("claude", args.claude, profile=args.profile) + drift(
        "codex", args.codex, required=bool(args.codex or shutil.which("codex")), profile=args.profile)
    if args.codex_trust:
        lines += _codex_trust()
    print("\n".join(lines) if lines else "hooks match manifest.json")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Fingerprints this machine's agent environment and, with --lock, diffs it against a
pinned env.lock. A sandbox whose fingerprint mismatches the lock must never link, so the
Mac, the devbox, and every sandbox run this one check (Oct 2026).

    python3 maintainer/env_fingerprint.py [--lock PATH] [--profile auto|darwin|linux|sandbox]
                                       [--codex-trust] [--json] [--kit PATH]

Each section prints `ok` or one line per drift; exit 1 on any drift, 2 on a lock that
isn't valid. Without --lock it runs only the checks that need no lock (a dirty kit or
yadm, a git status that fails or times out, dangling skill links, hooks vs manifest.json, a skill that differs from
~/.agents/.skill-lock.json, an unset git identity, a missing CLI) and prints what it
observed. `pinned` in the --json output is the lock-shaped part a lock writer copies.

Stdlib only, Python 3.10+, macOS and Linux. Read-only: git runs with optional locks
off, and it reads only names and hashes from files that can hold secrets (settings.json,
~/.claude.json, ~/.codex/config.toml). --codex-trust starts `codex app-server`, which
writes Codex state, so it's opt-in. Skill folders hash as git trees, the same SHA as
.skill-lock.json's skillFolderHash, without __pycache__/, *.pyc, and .DS_Store. Each
~/.claude/skills entry is recorded as a link (with its target) or a folder, with the tree
of what it resolves to. A file yadm doesn't track under an agent config folder is drift,
unless it's a link (its content is pinned by the kit or a tree) or a cache. That's the
lenient darwin and linux profiles; LENIENT_LIMITS lists what they don't see. --profile
sandbox is strict and needs --lock: every untracked or ignored entry under ~/.claude,
~/.agents and ~/.codex, minus RUNTIME_STATE, must be pinned by the lock, and bytecode in a
skill is drift. A skill tree outside the kit can't hold a symlink on any profile. Hooks
come from the manifest in the ADDYSTACK_KIT checkout (maintainer/kit_path.py), so point it
at an older kit to check a machine that runs one. ~/.codex/config.toml is compared with yadm HEAD as TOML, without the
keys the Codex app rewrites on its own (CODEX_APP_KEYS)."""
import argparse, fnmatch, hashlib, json, os, pathlib, re, shutil, subprocess, sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: every change to config.toml stays drift
    tomllib = None

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kit_path  # noqa: E402
sys.path.insert(0, str(kit_path.tool() / "hooks"))
import hook_parity  # noqa: E402
import render_hooks  # noqa: E402

LOCK_VERSION = 2  # 2: skills.claude maps each name to {kind, link, tree}; 1 listed names only
DEFAULT_AGENT_PATHS = [".claude/", ".agents/", ".codex/AGENTS.md", ".codex/rules/", ".codex/hooks.json",
                       ".codex/hooks/", ".config/yadm/", ".config/mise/"]
MATCHES = ("exact", "floor", "major")
SKIP = {"__pycache__", ".DS_Store", ".git"}
# Agent paths whose root also holds Claude Code's runtime state (projects/, sessions/,
# backups), so their untracked-file check covers only these config folders.
CONFIG_FOLDERS = {".claude/": [".claude/skills/", ".claude/hooks/", ".claude/agents/"]}
# Claude Code's own cache of skills synced from claude.ai (2.1.316 loads them as
# loadedFrom "syncedSkills"); it's per account, not part of the agent layer.
CLAUDE_CACHES = {"synced"}
KINDS = ("link", "folder")
# --profile sandbox is strict: a sandbox is trusted because it's built from the lock and
# nothing else, so every untracked or ignored entry under these (and the other agent paths)
# must be pinned by the lock. darwin and linux stay lenient (see LENIENT_LIMITS).
STRICT_ROOTS = (".claude/", ".agents/", ".codex/")
# What Claude Code and Codex write while they run, as seen on the devbox (2026-11-01). The
# strict check skips these and nothing else. A folder ends in "/"; a "*" stays in one folder.
RUNTIME_STATE = (
    ".claude/projects/", ".claude/sessions/", ".claude/session-env/", ".claude/shell-snapshots/",
    ".claude/todos/", ".claude/statsig/", ".claude/telemetry/", ".claude/state/", ".claude/cache/",
    ".claude/backups/", ".claude/plans/", ".claude/downloads/", ".claude/history.jsonl",
    ".claude/.credentials.json", ".claude/.last-cleanup", ".claude/.last-update-result.json",
    ".claude/mcp-needs-auth-cache.json",
    # Claude Code's plugin catalog, fetched on its own (a .gcs-sha, not a clone); which
    # plugins are on is settings.json's enabledPlugins, which settingsSha256 pins.
    ".claude/plugins/marketplaces/", ".claude/plugins/known_marketplaces.json",
    ".claude/plugins/plugin-directory-cache-v2.json", ".claude/plugins/.last_inuse_sweep",
    ".codex/sessions/", ".codex/log/", ".codex/shell_snapshots/", ".codex/tmp/", ".codex/cache/",
    ".codex/app-server-control/", ".codex/app-server-daemon/", ".codex/packages/", ".codex/thread-writer-locks/",
    ".codex/mcp-oauth-locks/", ".codex/tui-thread-reference-capabilities/",
    ".codex/skills/.system/",  # Codex's bundled skills, pinned by its exact version
    ".codex/auth.json", ".codex/installation_id", ".codex/version.json", ".codex/models_cache.json",
    ".codex/session_index.jsonl", ".codex/.sandbox_migration", ".codex/*.sqlite", ".codex/*.sqlite-shm",
    ".codex/*.sqlite-wal", ".codex/*.lock",
)
# What the lenient darwin and linux profiles don't see, by design: the Mac and devbox are
# where people work, so their homes hold state no lock pins. Only a sandbox is held to it.
LENIENT_LIMITS = (
    "ignored files under the agent paths",
    "untracked links (their targets aren't checked)",
    "~/.claude/ outside its skills/, hooks/ and agents/ folders (commands/, rules/, …)",
    "__pycache__/ and *.pyc inside skill trees",
    "~/.claude/skills/synced/ (Claude Code's claude.ai skill cache)",
)
# The leaf keys the Codex app rewrites in ~/.codex/config.toml as it runs, as seen on the
# Mac (2026-11-01), all strings: each hook's trusted hash, each project's trust level, and
# the app version its bundled node_repl runs from. "*" is any one table key. The version is
# also a folder in each path of CODEX_APP_PATHS (a JSON object of service paths), so HEAD's
# version is put in its place there before comparing.
CODEX_CONFIG = ".codex/config.toml"
CODEX_APP_VERSION = ("mcp_servers", "node_repl", "env", "BROWSER_USE_CODEX_APP_VERSION")
CODEX_APP_KEYS = (("hooks", "state", "*", "trusted_hash"), ("projects", "*", "trust_level"), CODEX_APP_VERSION)
CODEX_APP_PATHS = ("mcp_servers", "node_repl", "env", "NODE_REPL_TRUSTED_SERVICES")
SECTIONS = ("kit", "yadm", "globals", "skills", "hooks", "codex-trust", "settings", "mcp", "cli", "git")
GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GH_NO_UPDATE_NOTIFIER": "1", "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1"}
STATUS_FAILED = "{name}: {tool} status failed or timed out, so its cleanliness is unknown"
VERSION = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+)*(?:-[0-9A-Za-z.-]+)?)")


class LockError(ValueError):
    pass


def home():
    return pathlib.Path(os.path.expanduser("~"))


def run(*command, cwd=None, timeout=15):
    """stdout of command, stripped, or None when it's missing, fails, or times out."""
    if not shutil.which(command[0]):
        return None
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                stdin=subprocess.DEVNULL, env={**os.environ, **GIT_ENV})
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):  # output that isn't UTF-8 too
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None


def short(sha):
    return sha[:7] if sha else "none"


# --- git tree hashing --------------------------------------------------------------


def _object(kind, data):
    return hashlib.sha1(b"%s %d\0" % (kind, len(data)) + data).hexdigest()


def tree_sha(path):
    """The git tree SHA of folder path, as `git write-tree` would give for it, or None
    when it holds no files. Symlinks inside hash as links; the folder itself is followed."""
    entries = []
    try:
        children = list(os.scandir(path))
    except OSError:
        return None
    for child in children:
        if child.name in SKIP or child.name.endswith(".pyc"):
            continue
        name = child.name.encode("utf-8", "surrogateescape")
        if child.is_symlink():
            entries.append((name, b"120000", _object(b"blob", os.fsencode(os.readlink(child.path)))))
        elif child.is_dir():
            sub = tree_sha(child.path)
            if sub:
                entries.append((name + b"/", b"40000", sub))
        elif child.is_file():
            mode = b"100755" if child.stat().st_mode & 0o100 else b"100644"
            with open(child.path, "rb") as file:
                entries.append((name, mode, _object(b"blob", file.read())))
    if not entries:
        return None
    entries.sort()  # git orders a tree by name, a subtree's name with a trailing slash
    body = b"".join(mode + b" " + key.rstrip(b"/") + b"\0" + bytes.fromhex(sha) for key, mode, sha in entries)
    return _object(b"tree", body)


# --- sections ----------------------------------------------------------------------
# Each returns (observed, drift lines that need no lock).


def find_kit():
    """The checkout ~/.claude/skills/reply-shape links into, else the ADDYSTACK_KIT one
    (kit_path.py), which this script already loaded its hooks from."""
    link = home() / ".claude/skills/reply-shape"
    if link.exists():
        folder = link.resolve().parent
        # A checkout keeps each skill in skills/<layer>/<skill>.
        return folder.parent.parent if folder.parent.name == "skills" else folder
    return kit_path.repo()


def kit_section(path):
    path = pathlib.Path(path)
    sha = run("git", "-C", str(path), "rev-parse", "HEAD")
    if not sha:
        return ({"path": str(path), "sha": None, "dirty": [], "statusOk": False, "originMain": None},
                [f"kit: no git checkout at {path}"])
    status = run("git", "-C", str(path), "status", "--porcelain")
    dirty = status.splitlines() if status else []
    origin = run("git", "-C", str(path), "rev-parse", "--verify", "-q", "origin/main")
    lines = [f"kit: {line.strip()}" for line in dirty]
    if status is None:  # run() gives None on a failure or timeout, and "" when clean
        lines.append(STATUS_FAILED.format(name="kit", tool="git"))
    if origin and origin != sha:
        lines.append(f"kit: HEAD {short(sha)} ≠ origin/main {short(origin)}")
    return {"path": str(path), "sha": sha, "dirty": dirty, "statusOk": status is not None, "originMain": origin}, lines


def yadm_section(agent_paths, profile="darwin", kit=None):
    if not shutil.which("yadm"):
        return {"sha": None, "agentPaths": agent_paths, "dirty": [], "statusOk": False}, ["yadm: not installed"]
    sha = run("yadm", "rev-parse", "HEAD", cwd=home())
    paths = [p.lstrip("/") for p in agent_paths]
    pathspec = [*STRICT_ROOTS, *[p for p in paths if not p.startswith(STRICT_ROOTS)]]
    # Tracked changes count anywhere under ~/.claude, ~/.agents and ~/.codex, on every
    # profile: .codex/config.toml too, unless only CODEX_APP_KEYS changed.
    status = run("yadm", "status", "--porcelain", "--untracked-files=no", "--", *pathspec, cwd=home())
    dirty = [line for line in (status.splitlines() if status else []) if not codex_app_change(line)]
    strict = None
    if profile == "sandbox":  # every untracked and ignored entry; compare() checks each against the lock
        listing = run("yadm", "status", "--porcelain", "-z", "--untracked-files=all", "--ignored=matching", "--",
                      *pathspec, cwd=home())
        ok = status is not None and listing is not None
        strict = strict_entries(listing, kit)
    else:
        untracked = run("yadm", "status", "--porcelain", "-z", "--untracked-files=all", "--",
                        *[folder for p in paths for folder in CONFIG_FOLDERS.get(p, [p])], cwd=home())
        dirty += [f"?? {entry} (untracked, {count} file{'s' if count != 1 else ''})"
                  for entry, count in untracked_entries(untracked).items()]
        ok = status is not None and untracked is not None
    lines = [] if sha else ["yadm: no HEAD"]
    lines += [f"yadm: {line.strip()}" for line in dirty]
    if not ok:
        lines.append(STATUS_FAILED.format(name="yadm", tool="yadm"))
    observed = {"sha": sha, "agentPaths": agent_paths, "dirty": dirty, "statusOk": ok}
    if strict is not None:
        observed["strict"] = strict
    return observed, lines


def _drop(table, path):
    """Removes each string at the key path ("*" is any key), and each table that leaves
    empty, from table; returns the strings removed."""
    if not isinstance(table, dict):
        return []
    head, *rest = path
    if not rest:
        return [table.pop(head)] if isinstance(table.get(head), str) else []
    removed = []
    for key in list(table) if head == "*" else [head] if head in table else []:
        dropped = _drop(table[key], rest)
        if dropped and table[key] == {}:
            del table[key]
        removed += dropped
    return removed


def _typed(value):
    """value with each scalar tagged by its type, since True == 1 in Python but not in TOML."""
    if isinstance(value, dict):
        return {key: _typed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_typed(item) for item in value]
    return (type(value).__name__, value)


def _settled(text):
    """(config.toml without CODEX_APP_KEYS, the app version it held), or None when it isn't
    TOML or nests too deep to compare."""
    try:
        config = tomllib.loads(text)
        versions = _drop(config, CODEX_APP_VERSION)
        for path in CODEX_APP_KEYS:
            _drop(config, path)
    except (TypeError, ValueError, RecursionError):
        return None
    return config, (versions or [None])[0]


def _with_version(config, version, want):
    """Rewrites CODEX_APP_PATHS's service paths with the version want in place of version.
    Only a JSON object of string paths is rewritten, and its names never are; any other
    value stays as it is, so a version change there is drift."""
    *parents, key = CODEX_APP_PATHS
    table = config
    for parent in parents:
        table = table.get(parent) if isinstance(table, dict) else None
    try:
        services = json.loads(table[key]) if isinstance(table, dict) and isinstance(table.get(key), str) else None
    except (ValueError, RecursionError):
        return
    if isinstance(services, dict) and all(isinstance(path, str) for path in services.values()):
        table[key] = canonical({name: path.replace(f"/{version}/", f"/{want}/") if version and want else path
                                for name, path in services.items()})


def _only_app_keys_differ(head_text, text):
    head, now = _settled(head_text), _settled(text)
    if head is None or now is None:
        return False
    (head, head_version), (now, version) = head, now
    _with_version(head, head_version, head_version)  # the same rewrite on both sides
    _with_version(now, version, head_version)
    try:
        return _typed(head) == _typed(now)
    except RecursionError:
        return False


def codex_app_change(line):
    """Whether a `status --porcelain` line is config.toml changed only in CODEX_APP_KEYS,
    in both the index and the work tree."""
    state, _, path = line.strip().partition(" ")
    if path.strip() != CODEX_CONFIG or state not in ("M", "MM") or tomllib is None:
        return False
    for against in ("--cached", "HEAD"):  # `:old new …` per changed file; a mode change is drift
        raw = run("yadm", "diff", against, "--raw", "--", CODEX_CONFIG, cwd=home())
        if raw is None or any(line.split()[0] != ":" + line.split()[1] for line in raw.splitlines()):
            return False
    head, index = (run("yadm", "show", f"{rev}:{CODEX_CONFIG}", cwd=home()) for rev in ("HEAD", ""))
    try:
        now = (home() / CODEX_CONFIG).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return head is not None and all(text is not None and _only_app_keys_differ(head, text) for text in (index, now))


def _runtime(path):
    for pattern in RUNTIME_STATE:
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if fnmatch.fnmatch(path, pattern) and path.count("/") == pattern.count("/"):
            return True
    return False


def strict_entries(porcelain, kit):
    """Each untracked (??) or ignored (!!) entry from `status --porcelain -z`, without
    runtime state, as {path, state, link, inKit, alternate}. Files under a skill folder
    collapse to the folder, `.claude/skills/<name>/`."""
    entries = {}
    for record in (porcelain or "").split("\0"):
        state, path = record[:2], record[3:]
        if state not in ("??", "!!") or _runtime(path):
            continue
        parts = path.rstrip("/").split("/")
        if parts[1:2] == ["skills"] and parts[0] in (".claude", ".agents") and len(parts) >= 3:
            path = "/".join(parts[:3]) + ("/" if len(parts) > 3 or path.endswith("/") else "")
        if path in entries:
            continue
        full = home() / path.rstrip("/")
        link = os.path.realpath(full) if os.path.islink(full) else None
        alternate = bool(link) and os.path.dirname(link) == os.path.realpath(full.parent) \
            and os.path.basename(link).startswith(full.name + "##")  # yadm's `name##os.Linux` link
        entries[path] = {"path": path, "state": state, "link": link,
                         "inKit": bool(link and kit and _inside(link, kit)), "alternate": alternate}
    return [entries[path] for path in sorted(entries)]


def untracked_entries(porcelain):
    """Untracked files from `status --porcelain -z`, counted per top entry of their config
    folder (`.claude/skills/use-railway/`). Links don't count, since their content is pinned
    by the kit SHA or a skill tree, and neither do what tree_sha skips or a Claude cache."""
    counts = {}
    for record in (porcelain or "").split("\0"):
        if not record.startswith("?? "):
            continue
        path = record[3:]
        parts = pathlib.PurePosixPath(path).parts
        if (any(part in SKIP or part.endswith(".pyc") for part in parts) or os.path.islink(home() / path)
                or path.startswith(tuple(f".claude/skills/{cache}/" for cache in CLAUDE_CACHES))):
            continue
        folder = next((f for folders in CONFIG_FOLDERS.values() for f in folders if path.startswith(f)), None)
        depth = len(pathlib.PurePosixPath(folder).parts) if folder else len(parts) - 1
        entry = "/".join(parts[:depth + 1]) + ("/" if len(parts) > depth + 1 else "")
        counts[entry] = counts.get(entry, 0) + 1
    return dict(sorted(counts.items()))


def globals_section(kit):
    observed, lines = {}, []
    for key, relative in (("claudeMd", ".claude/CLAUDE.md"), ("agentsMd", ".codex/AGENTS.md")):
        path = home() / relative
        try:
            observed[f"{key}Sha256"] = sha256(path.read_bytes())
        except OSError:
            observed[f"{key}Sha256"] = None
            lines.append(f"globals: ~/{relative} is missing")
        observed[f"{key}Link"] = os.readlink(path) if path.is_symlink() else None
    script = pathlib.Path(kit, "maintainer/build-global.py")
    if script.exists():
        result = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        observed["buildCheck"] = result.returncode == 0
        if result.returncode:
            lines.append("globals: build-global.py --check: " + " ".join(result.stderr.split()))
    else:
        observed["buildCheck"] = None
    return observed, lines


def _skill_dir(folder, skip=()):
    entries, dangling = {}, []
    if not folder.is_dir():
        return entries, dangling
    for entry in sorted(folder.iterdir()):
        if entry.name in skip:
            continue
        link = os.readlink(entry) if entry.is_symlink() else None
        if link is not None and not entry.exists():
            dangling.append(entry.name)
            entries[entry.name] = {"link": link, "tree": None}
        elif entry.is_dir():
            entries[entry.name] = {"link": link, "tree": tree_sha(entry)}
    return entries, dangling


def _inside(path, folder):
    return pathlib.Path(path).resolve().is_relative_to(pathlib.Path(folder).resolve())


def _skill_trees(kit, *folders, with_kit=False):
    """(label, resolved folder) for each skill folder, once per resolved path, and outside
    the kit unless with_kit. A kit skill's content, its own links included, is pinned by the
    kit SHA."""
    seen = set()
    for folder in folders:
        for entry in sorted(folder.iterdir()) if folder.is_dir() else []:
            resolved = entry.resolve()
            if entry.name in CLAUDE_CACHES or not resolved.is_dir() or resolved in seen or (
                    not with_kit and _inside(resolved, kit)):
                continue
            seen.add(resolved)
            yield f"~/{entry.relative_to(home())}", resolved


def _listed(paths):
    return ", ".join(paths[:3]) + (f", +{len(paths) - 3}" if len(paths) > 3 else "")


def nested_links(folder):
    """Paths of the symlinks inside folder, which restore-agent-skills refuses in a skill."""
    links = []
    for root, dirs, files in os.walk(folder):
        links += [os.path.relpath(os.path.join(root, name), folder) for name in [*dirs, *files]
                  if os.path.islink(os.path.join(root, name))]
    return sorted(links)


def bytecode(folder):
    """Paths of the *.pyc files inside folder, which tree_sha skips."""
    found = []
    for root, dirs, files in os.walk(folder):
        found += [os.path.relpath(os.path.join(root, name), folder) for name in files
                  if name.endswith(".pyc")]
    return sorted(found)


def skills_section(kit, profile="darwin"):
    agents, agents_dangling = _skill_dir(home() / ".agents/skills")
    claude, claude_dangling = _skill_dir(home() / ".claude/skills", skip=CLAUDE_CACHES)
    lines = [f"skills: dangling link ~/.agents/skills/{name} → {agents[name]['link']}" for name in agents_dangling]
    lines += [f"skills: dangling link ~/.claude/skills/{name} → {claude[name]['link']}" for name in claude_dangling]
    lock = read_json(home() / ".agents/.skill-lock.json")
    rows = lock.get("skills") if isinstance(lock, dict) else None
    skill_lock = None
    if isinstance(rows, dict):
        skill_lock = {}
        for name, row in sorted(rows.items()):
            if not isinstance(row, dict):
                continue
            skill_lock[name] = {"source": row.get("source"),
                                "skillPath": re.sub(r"/?SKILL\.md$", "", row.get("skillPath") or ""),
                                "skillFolderHash": row.get("skillFolderHash")}
            have = agents.get(name, {}).get("tree")
            if name not in agents:
                lines.append(f"skills: {name} is in .skill-lock.json but not installed")
            elif have and have != row.get("skillFolderHash"):
                lines.append(f"skills: {name} tree {short(have)} ≠ .skill-lock.json {short(row.get('skillFolderHash'))}")
    claude = {name: {"kind": "link" if row["link"] is not None else "folder", **row} for name, row in claude.items()}
    for label, folder in _skill_trees(kit, home() / ".agents/skills", home() / ".claude/skills"):
        links = nested_links(folder)
        if links:
            lines.append(f"skills: {label} holds a symlink ({_listed(links)}), which a skill tree can't have")
    if profile == "sandbox":  # tree_sha skips bytecode, so a sandbox's skills must have none
        for label, folder in _skill_trees(kit, home() / ".agents/skills", home() / ".claude/skills", with_kit=True):
            found = bytecode(folder)
            if found:
                lines.append(f"skills: {label} holds bytecode ({_listed(found)}), which a sandbox can't have")
    observed = {"agents": agents, "claude": claude, "dangling": sorted(
        [f"~/.agents/skills/{n}" for n in agents_dangling] + [f"~/.claude/skills/{n}" for n in claude_dangling]),
        "skillLock": skill_lock}
    return observed, lines


def hooks_sha256(hooks):
    """sha256 of a `hooks` object's events, groups, and hooks, in their order, since Codex
    trusts a hook by its position; formatting and unknown keys don't count."""
    if not isinstance(hooks, dict):
        return None
    shape = {event: [{"matcher": group.get("matcher") or None,
                      "hooks": [{key: hook.get(key) for key in ("command", "timeout", "onFailure")}
                                for hook in group.get("hooks") or [] if isinstance(hook, dict)]}
                     for group in groups if isinstance(group, dict)]
             for event, groups in hooks.items() if isinstance(groups, list)}
    return sha256(canonical(shape))


def installed_hooks_sha256(path):
    config = read_json(path)
    return hooks_sha256(config.get("hooks")) if isinstance(config, dict) else None


def rendered_hooks_sha256(runtime, profile):
    return hooks_sha256(render_hooks.render(runtime, profile))


def hooks_section(profile, codex_installed):
    lines = hook_parity.drift("claude", profile=profile) + hook_parity.drift(
        "codex", required=codex_installed, profile=profile)
    observed = {
        "manifestSha256": sha256(hook_parity.MANIFEST.read_bytes()),
        "installedSha256": {runtime: installed_hooks_sha256(pathlib.Path(path).expanduser())
                            for runtime, path in hook_parity.PATHS.items()},
        "renderedSha256": {f"{runtime}:{name}": rendered_hooks_sha256(runtime, name)
                           for runtime in hook_parity.PATHS for name in hook_parity.PROFILES},
    }
    return observed, lines


def settings_section():
    settings = read_json(home() / ".claude/settings.json")
    if not isinstance(settings, dict):
        return {"sha256": None}, ["settings: ~/.claude/settings.json is missing or not JSON"]
    rest = {key: value for key, value in settings.items() if key not in ("hooks", "permissions")}
    return {"sha256": sha256(canonical(rest))}, []


def mcp_section():
    claude = read_json(home() / ".claude.json")
    servers = claude.get("mcpServers") if isinstance(claude, dict) else None
    lines = []
    try:
        toml = (home() / ".codex/config.toml").read_text(encoding="utf-8")
    except OSError:
        toml = ""
    except UnicodeDecodeError:
        toml, lines = "", ["mcp: ~/.codex/config.toml isn't UTF-8, so its servers are unknown"]
    codex = re.findall(r'^\s*\[mcp_servers\.(?:"([^"]+)"|([A-Za-z0-9_-]+))\]\s*$', toml, re.M)
    return {"claude": sorted(servers) if isinstance(servers, dict) else [],
            "codex": sorted({quoted or bare for quoted, bare in codex})}, lines


def _version(text):
    match = VERSION.search(text or "")
    return match.group(1) if match else None


def cli_section():
    versions = {}
    for name in ("claude", "codex", "t3", "gh", "node"):
        versions[name] = _version(run(name, "--version"))
    extensions = run("gh", "extension", "list") or ""
    stack = next((line for line in extensions.splitlines() if "gh-stack" in line or line.startswith("gh stack")), "")
    versions["gh-stack"] = _version(stack.split("\t")[-1] if "\t" in stack else stack)
    # The skills CLI runs through npx at the version bootstrap step 40 pins, so read the pin:
    # `npx skills --version` would install it or write an npm log.
    pins = read_json(home() / ".config/yadm/agent-skills.json")
    pin = pins.get("cli") if isinstance(pins, dict) else None
    versions["skills"] = _version(pin) if isinstance(pin, str) else None
    lines = [f"cli: {name} not found" for name, version in versions.items() if version is None]
    return {name: {"version": version} for name, version in versions.items()}, lines


def git_section():
    observed = {key: run("git", "config", "--global", "--get", key, cwd=home()) for key in ("user.name", "user.email")}
    return observed, [f"git: {key} unset" for key, value in observed.items() if value is None]


# --- the lock ----------------------------------------------------------------------


def pinned(observed, profile):
    """The lock-shaped values of an observed fingerprint: what a lock writer copies, before
    it adds version, createdAt, each CLI's match rule, and profiles."""
    skills = observed["skills"]
    return {
        "kit": {"sha": observed["kit"]["sha"]},
        "yadm": {"sha": observed["yadm"]["sha"], "agentPaths": observed["yadm"]["agentPaths"]},
        "cli": observed["cli"],
        "git": observed["git"],
        "skills": {"agents": sorted(skills["agents"]),
                   "claude": {name: {"kind": row["kind"], "link": row["link"], "tree": row["tree"]}
                              for name, row in sorted(skills["claude"].items())}},
        "remoteSkills": {name: {"source": row["source"], "skillPath": row["skillPath"],
                                "tree": skills["agents"].get(name, {}).get("tree")}
                         for name, row in (skills["skillLock"] or {}).items()},
        "hooks": {"manifestSha256": observed["hooks"]["manifestSha256"],
                  "renderedSha256": observed["hooks"]["renderedSha256"]},
        "globals": {"claudeMdSha256": observed["globals"]["claudeMdSha256"],
                    "agentsMdSha256": observed["globals"]["agentsMdSha256"]},
        "settingsSha256": observed["settings"]["sha256"],
        "mcp": {profile: observed["mcp"]},
    }


def _need(condition, message):
    if not condition:
        raise LockError(message)


def validate(lock):
    """Raises LockError naming the first thing a lock lacks or gets wrong."""
    _need(isinstance(lock, dict), "a lock is a JSON object")
    _need(lock.get("version") != 1, "a version 1 lock records ~/.claude/skills by name only; rewrite it with sbx lock")
    _need(lock.get("version") == LOCK_VERSION, f"version must be {LOCK_VERSION}")
    sha = re.compile(r"^[0-9a-f]{40}$")
    digest = re.compile(r"^[0-9a-f]{64}$")
    for key in ("kit", "yadm"):
        _need(isinstance(lock.get(key), dict) and sha.match(str(lock[key].get("sha"))), f"{key}.sha must be a 40-hex SHA")
    paths = lock["yadm"].get("agentPaths", DEFAULT_AGENT_PATHS)
    _need(isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths), "yadm.agentPaths must list paths")
    cli = lock.get("cli")
    _need(isinstance(cli, dict) and cli, "cli must map each CLI to {version, match}")
    for name, pin in cli.items():
        _need(isinstance(pin, dict) and isinstance(pin.get("version"), str) and _version(pin["version"]),
              f"cli.{name}.version must be a version")
        _need(pin.get("match") in MATCHES, f"cli.{name}.match must be one of {', '.join(MATCHES)}")
    git = lock.get("git")
    _need(isinstance(git, dict) and all(isinstance(git.get(k), str) for k in ("user.name", "user.email")),
          "git must hold user.name and user.email")
    skills = lock.get("skills")
    _need(isinstance(skills, dict) and isinstance(skills.get("agents"), list), "skills.agents must list names")
    _need(isinstance(skills.get("claude"), dict), "skills.claude must map each name to {kind, link, tree}")
    for name, row in skills["claude"].items():
        _need(isinstance(row, dict) and row.get("kind") in KINDS and "link" in row
              and (row["link"] is None) == (row["kind"] == "folder") and (row["link"] is None or isinstance(row["link"], str))
              and sha.match(str(row.get("tree"))),
              f"skills.claude.{name} must be {{kind: link|folder, link: target or null, tree: 40-hex SHA}}")
    remote = lock.get("remoteSkills")
    _need(isinstance(remote, dict), "remoteSkills must map names to {source, skillPath, tree}")
    for name, row in remote.items():
        _need(isinstance(row, dict) and sha.match(str(row.get("tree"))), f"remoteSkills.{name}.tree must be a 40-hex SHA")
    hooks = lock.get("hooks")
    _need(isinstance(hooks, dict) and digest.match(str(hooks.get("manifestSha256"))), "hooks.manifestSha256 must be a sha256")
    _need(isinstance(hooks.get("renderedSha256"), dict), "hooks.renderedSha256 must map runtime:profile to a sha256")
    globals_ = lock.get("globals")
    _need(isinstance(globals_, dict) and all(digest.match(str(globals_.get(k))) for k in ("claudeMdSha256", "agentsMdSha256")),
          "globals must hold claudeMdSha256 and agentsMdSha256")
    _need(digest.match(str(lock.get("settingsSha256"))), "settingsSha256 must be a sha256")
    _need(isinstance(lock.get("mcp"), dict), "mcp must map each profile to {claude, codex} names")
    profiles = lock.get("profiles", {})
    _need(isinstance(profiles, dict) and set(profiles) <= set(hook_parity.PROFILES),
          f"profiles must be among {', '.join(hook_parity.PROFILES)}")
    for name, rules in profiles.items():
        _need(isinstance(rules, dict), f"profiles.{name} must be an object")
        _need(rules.get("extends") in (None, *profiles), f"profiles.{name}.extends must name another profile")
        excludes = rules.get("exclude", [])
        _need(isinstance(excludes, list) and all(re.match(r"^(skill|mcp):\S+$", str(e)) for e in excludes),
              f"profiles.{name}.exclude must list skill:<name> or mcp:<name>")


def excluded(lock, profile, seen=()):
    """The `kind:name` exclusions profile gets, its extends chain's included."""
    rules = lock.get("profiles", {}).get(profile, {})
    parent = rules.get("extends")
    inherited = excluded(lock, parent, (*seen, profile)) if parent and parent not in seen else set()
    return set(rules.get("exclude", [])) | inherited


def _numbers(version):
    return tuple(int(part) for part in re.findall(r"\d+", version.split("-")[0]))


def version_ok(have, pin):
    want = _version(pin["version"])
    if have is None:
        return False
    if pin["match"] == "exact":
        return have == want
    if pin["match"] == "major":
        return _numbers(have)[:1] == _numbers(want)[:1]
    return _numbers(have) >= _numbers(want)


def _strict_compare(observed, lock, skip, claude_names, drift):
    """Under --profile sandbox, each untracked or ignored entry must be pinned by the lock:
    a skill the lock names (a remote one as a real folder, a kit one as a link into the
    kit), a link into the locked kit, or a yadm alternate link to its tracked target."""
    agents_names = {name for name in lock["skills"]["agents"] if f"skill:{name}" not in skip}
    untracked = {entry["path"].rstrip("/") for entry in observed["yadm"].get("strict") or []}
    unpinned = {}
    for entry in observed["yadm"].get("strict") or []:
        parts = entry["path"].rstrip("/").split("/")
        if parts[:3] == [".claude", "skills", "synced"]:
            drift["yadm"].append("yadm: ~/.claude/skills/synced holds claude.ai skills, which a sandbox can't have")
            continue
        skill = parts[2] if len(parts) == 3 and parts[1] == "skills" else None
        if parts[0] == ".claude" and skill in claude_names:
            continue  # its kind, link and tree are compared below
        if parts[0] == ".agents" and skill in agents_names and (
                entry["inKit"] if entry["link"] else skill in lock["remoteSkills"]):
            continue
        if entry["inKit"]:
            continue
        if entry["alternate"] and os.path.relpath(entry["link"], os.path.realpath(home())) not in untracked:
            continue
        unpinned.setdefault("/".join(parts[:2]) + ("/" if len(parts) > 2 else ""), []).append(entry)
    for folder, entries in unpinned.items():  # one line per folder, so a big cache reads as one line
        states = "/".join(sorted({entry["state"] for entry in entries}))
        what = entries[0]["path"] if len(entries) == 1 else f"{folder} ({len(entries)} entries)"
        drift["yadm"].append(f"yadm: {states} {what} isn't tracked by yadm or pinned by the lock")


def _entry(row):
    return f"a link to {row['link']}" if row["kind"] == "link" else "a folder"


def compare(observed, lock, profile):
    """Drift lines per section between observed and a validated lock."""
    drift = {name: [] for name in SECTIONS}
    skip = excluded(lock, profile)

    def pin(section, label, have, want):
        if have != want:
            drift[section].append(f"{section}: {label} {short(have) if section != 'git' else have or 'unset'} ≠ lock "
                                  f"{short(want) if section != 'git' else want}")

    for name, tool in (("kit", "git"), ("yadm", "yadm")):
        if observed[name].get("statusOk") is not True:  # an observation without the flag can't show it's clean
            drift[name].append(STATUS_FAILED.format(name=name, tool=tool))
    pin("kit", "HEAD", observed["kit"]["sha"], lock["kit"]["sha"])
    pin("yadm", "HEAD", observed["yadm"]["sha"], lock["yadm"]["sha"])
    for key in ("claudeMdSha256", "agentsMdSha256"):
        pin("globals", key.replace("Sha256", ""), observed["globals"][key], lock["globals"][key])
    pin("settings", "sha256", observed["settings"]["sha256"], lock["settingsSha256"])
    for key in ("user.name", "user.email"):
        pin("git", key, observed["git"][key], lock["git"][key])

    skills = observed["skills"]
    claude_want = {name: row for name, row in lock["skills"]["claude"].items() if f"skill:{name}" not in skip}
    for name in sorted(set(claude_want) & set(skills["claude"])):
        have, want = skills["claude"][name], claude_want[name]
        if (have["kind"], have["link"]) != (want["kind"], want["link"]):
            drift["skills"].append(f"skills: ~/.claude/skills/{name} is {_entry(have)}; lock has {_entry(want)}")
        elif have["tree"] != want["tree"]:
            drift["skills"].append(f"skills: ~/.claude/skills/{name} tree {short(have['tree'])} ≠ lock {short(want['tree'])}")
    if profile == "sandbox":
        _strict_compare(observed, lock, skip, set(claude_want), drift)
    for where, have in (("agents", set(skills["agents"])), ("claude", set(skills["claude"]))):
        want = {name for name in lock["skills"][where] if f"skill:{name}" not in skip}
        folder = "~/.agents/skills" if where == "agents" else "~/.claude/skills"
        drift["skills"] += [f"skills: missing {folder}/{name}" for name in sorted(want - have)]
        drift["skills"] += [f"skills: extra {folder}/{name}" for name in sorted(have - want)]
    for name, row in sorted(lock["remoteSkills"].items()):
        have = skills["agents"].get(name, {}).get("tree")
        if f"skill:{name}" not in skip and name in skills["agents"] and have != row["tree"]:
            drift["skills"].append(f"skills: {name} tree {short(have)} ≠ lock {short(row['tree'])}")

    hooks = observed["hooks"]
    pin("hooks", "manifest", hooks["manifestSha256"], lock["hooks"]["manifestSha256"])
    for runtime, have in hooks["installedSha256"].items():
        want = lock["hooks"]["renderedSha256"].get(f"{runtime}:{profile}")
        if want is None:
            drift["hooks"].append(f"hooks: lock has no renderedSha256 for {runtime}:{profile}")
        elif have != want:
            drift["hooks"].append(f"hooks: {runtime} installed {short(have)} ≠ lock {runtime}:{profile} {short(want)}")

    want_mcp = lock["mcp"].get(profile)
    if not isinstance(want_mcp, dict):
        drift["mcp"].append(f"mcp: lock has no {{claude, codex}} server names for profile {profile}")
    else:
        for runtime in ("claude", "codex"):
            want = {name for name in want_mcp.get(runtime, []) if f"mcp:{name}" not in skip}
            have = set(observed["mcp"][runtime])
            drift["mcp"] += [f"mcp: {runtime} missing {name}" for name in sorted(want - have)]
            drift["mcp"] += [f"mcp: {runtime} extra {name}" for name in sorted(have - want)]

    for name, rule in sorted(lock["cli"].items()):
        have = observed["cli"].get(name, {}).get("version")
        if not version_ok(have, rule):
            drift["cli"].append(f"cli: {name} {have or 'not found'} ≠ lock {_version(rule['version'])} ({rule['match']})")
    return drift


# --- output ------------------------------------------------------------------------


def summary(name, observed):
    value = observed.get(name)
    if name == "kit":
        return f"{short(value['sha'])} {'clean' if not value['dirty'] else 'dirty'}"
    if name == "yadm":
        return f"{short(value['sha'])}"
    if name == "skills":
        return f"{len(value['agents'])} in ~/.agents/skills, {len(value['claude'])} in ~/.claude/skills"
    if name == "cli":
        return ", ".join(f"{cli} {pin['version'] or '-'}" for cli, pin in value.items())
    if name == "git":
        return f"{value['user.name'] or '-'} <{value['user.email'] or '-'}>"
    if name == "mcp":
        return "; ".join(f"{runtime}: {', '.join(names) or '-'}" for runtime, names in value.items())
    if name == "settings":
        return short(value["sha256"])
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", help="an env.lock JSON file to diff against")
    parser.add_argument("--profile", default="auto", choices=("auto", *hook_parity.PROFILES))
    parser.add_argument("--codex-trust", action="store_true", help="also ask codex app-server which hooks it trusts")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--kit", help="the kit checkout (default: where ~/.claude/skills/reply-shape links, else ADDYSTACK_KIT's)")
    args = parser.parse_args(argv)
    profile = hook_parity.host_profile(args.profile)

    lock, lock_sha = None, None
    if args.lock:
        try:
            raw = pathlib.Path(args.lock).expanduser().read_bytes()
            lock = json.loads(raw)
            validate(lock)
        except (OSError, ValueError) as error:
            print(f"env_fingerprint: invalid lock {args.lock}: {error}", file=sys.stderr)
            return 2
        lock_sha = sha256(raw)

    kit = pathlib.Path(args.kit).expanduser() if args.kit else find_kit()
    agent_paths = lock["yadm"].get("agentPaths", DEFAULT_AGENT_PATHS) if lock else DEFAULT_AGENT_PATHS
    observed, drift = {}, {}
    for name, probe in (("kit", lambda: kit_section(kit)), ("yadm", lambda: yadm_section(agent_paths, profile, kit)),
                        ("globals", lambda: globals_section(kit)), ("skills", lambda: skills_section(kit, profile)),
                        ("hooks", lambda: hooks_section(profile, bool(shutil.which("codex")))),
                        ("settings", settings_section), ("mcp", mcp_section), ("cli", cli_section),
                        ("git", git_section)):
        observed[name], drift[name] = probe()
    if profile == "sandbox" and not lock:
        drift["yadm"].append("yadm: the sandbox profile checks against a lock; pass --lock")
    if args.codex_trust:
        observed["codex-trust"], drift["codex-trust"] = {}, hook_parity._codex_trust()
    if lock:
        for name, lines in compare(observed, lock, profile).items():
            if name in drift:
                drift[name] += [line for line in lines if line not in drift[name]]
    pins = pinned(observed, profile)
    fingerprint = sha256(canonical(pins))
    sections = {name: {"ok": not drift[name], "drift": drift[name], "observed": observed[name]}
                for name in SECTIONS if name in drift}
    failed = any(drift.values())

    if args.json:
        print(json.dumps({"profile": profile, "lock": args.lock, "lockSha256": lock_sha, "fingerprint": fingerprint,
                          "ok": not failed, "sections": sections, "pinned": pins}, indent=2, ensure_ascii=False))
    else:
        where = f"lock {short(lock_sha)} ({args.lock})" if lock else "no lock"
        print(f"env fingerprint · profile {profile} · {where}")
        for name, section in sections.items():
            if section["ok"]:
                print(f"{name:<11}ok    {summary(name, observed)}".rstrip())
            for index, line in enumerate(section["drift"]):
                print(f"{name if index == 0 else '':<11}DRIFT {line}")
        print(f"fingerprint {fingerprint[:12]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

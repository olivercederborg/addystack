"""Loads, validates, and merges addystack's config layers into one Resolved value.

This is the only module that knows layer files exist. The layers, in order:

1. the kit's `addystack.defaults.jsonc`;
2. the user's `~/.config/addystack/addystack.jsonc`, or without one, a `global.md` beside
   where it would be, as that layer's `instructions`.

The kit ships no team presets, so a config has no `extends`, and skills install with `npx
skills add`, so it has no `skills`: validate() reports a config that still has either, with
what to do instead. A team's rules are `policy.repos` rules in the
user's config; the repo's own `.agents/addystack.jsonc` holds only `planning`, `trust`,
and `pushVia`, and can only make them stricter. Objects deep-merge, a later
scalar wins, and arrays replace, except that `policy.repos` concatenates in layer order,
the hooks `enable`/`disable` lists apply as set operations in layer order, and
`judgment.principles.exclude` lists are combined. Each relative path (`replies.rules`,
`judgment.taste`, `instructions`, a lens file) resolves against its own layer's folder
and is stored absolute. Every layer is JSONC: `//` and `/* */` comments are stripped
outside strings before parsing, and each is checked against `schema/v1.json`.

Each layer may set `instructions`, so Resolved keeps them all, in layer order. A lens
naming a file (it holds a `/` or ends in `.md`) is a path; any other lens is a skill name.
`policy.unresolved` takes, per field, the strictest value across the defaults and every
rule: gated over autonomous, draft over merge-on-go over gate, gh-stack over git, a
Decisions section over none, and every lens. `issues` and `verifySkill` come from the
strictest rule that sets them, ranking each rule by its trust, then planning, then
pushVia over the defaults; the earlier rule wins a tie.

`ADDYSTACK_CONFIG` overrides CONFIG's path, for tests and dry runs. Inside `planned`, the
config, the files it names, and render's reads of them see a dry run's planned text instead
of the disk's.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, TypedDict

CONFIG = Path(os.environ.get("ADDYSTACK_CONFIG", "~/.config/addystack/addystack.jsonc"))
# The user's instructions file beside the config, which install adopts the hosts' text into.
GLOBAL = "global.md"


def claude_home() -> Path:
    """Claude Code's folder, absolute: $CLAUDE_CONFIG_DIR, trimmed, when it isn't blank, else
    ~/.claude, as the skills CLI (v1.7.6 `claudeHome`) reads it. Like the CLI, it doesn't
    expand a `~` in the variable, reads a relative one from the working directory, and folds
    `..` by its text, as Node's path functions do, so every caller reads and writes the same
    files. Read on each call, so the environment of the moment counts."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(os.path.abspath(configured)) if configured else Path("~/.claude").expanduser()


# Absolute path -> text, set by planned() for a dry run.
_PLANNED: Dict[str, str] = {}


@contextlib.contextmanager
def planned(files: Mapping[Path, str]) -> Iterator[None]:
    """Within it, each path in files reads as its text and counts as a file, so install
    --dry-run previews the build from the state its writes would leave."""
    saved = dict(_PLANNED)
    _PLANNED.update({os.path.abspath(path): text for path, text in files.items()})
    try:
        yield
    finally:
        _PLANNED.clear()
        _PLANNED.update(saved)


def read_text(path: Path) -> str:
    """path's text, or its planned text inside planned()."""
    planned_text = _PLANNED.get(os.path.abspath(path))
    return Path(path).read_text() if planned_text is None else planned_text


def _is_file(path: Path) -> bool:
    return os.path.abspath(path) in _PLANNED or Path(path).is_file()


@dataclass(frozen=True)
class Layer:
    """One parsed config file: `name` is `defaults` or `user`."""
    name: str
    dir: Path
    data: Dict[str, Any]


@dataclass(frozen=True)
class Issue:
    """One validation failure, at a dotted key path, as `replies.style: not one of
    reply-shape, own`."""
    path: str
    message: str


class Invalid(Exception):
    """Raised by resolve() when any layer fails validation."""

    def __init__(self, issues: List[Issue]) -> None:
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in issues))
        self.issues = issues


class Match(TypedDict, total=False):
    """A repo rule's condition. Every key given must hold: `remote` is a regex matched
    against the origin URL, case-insensitively, and `path` a glob matched against the
    checkout's root."""
    remote: str
    path: str


class Rule(TypedDict):
    """A `policy.repos` entry after merging: its condition, the Policy fields it sets,
    and where it came from, such as `user#0`."""
    match: Match
    set: Dict[str, Any]
    source: str


class PolicyTable(TypedDict):
    """`defaults` and `unresolved` are full Policy field sets; `unresolved` is the
    strictest value of each field across the defaults and every rule."""
    defaults: Dict[str, Any]
    unresolved: Dict[str, Any]
    rules: List[Rule]


class CheckQueue(TypedDict):
    """The `checkQueue` section after merging: the agent memory guard's check queue."""
    enabled: bool
    maxChecks: int
    maxCores: int


class Resolved(TypedDict):
    """The merged config that build writes to resolved.json. `kit` is the installed
    checkout's absolute path, `layers` names the layers merged, and `digest` hashes the
    inputs so doctor can tell a stale build."""
    version: int
    kit: str
    layers: List[str]
    digest: str
    identity: Dict[str, str]
    hosts: Dict[str, Any]
    replies: Dict[str, Any]
    policy: PolicyTable
    judgment: Dict[str, Any]
    instructions: List[str]
    hooks: Dict[str, Any]


_KIT = Path(__file__).resolve().parent.parent
_POLICY_FIELDS = ("planning", "trust", "pushVia", "issues", "lenses", "verifySkill", "decisionsSection")
# How strict each value is; a higher rank is stricter.
_RANK = {
    "planning": {"autonomous": 0, "gated": 1},
    # gate merges once the merge-gate hook allows it, with no go; merge-on-go also waits for
    # the user's go, so it's the stricter of the two.
    "trust": {"gate": 0, "merge-on-go": 1, "draft": 2},
    "pushVia": {"git": 0, "gh-stack": 1},
}
# The schema keywords validate() evaluates, and the ones it reads as annotations only.
_ASSERTIONS = frozenset({"type", "enum", "const", "properties", "additionalProperties", "items", "$ref",
                         "required", "minProperties"})
_ANNOTATIONS = frozenset({"$schema", "$id", "title", "default", "markdownDescription", "definitions"})
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def strip_comments(text: str) -> str:
    """JSONC text with its comments removed, keeping strings intact, for json.loads."""
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            end = i + 1
            while end < n and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i:end + 1])
            i = end + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                # Unterminated: keep it, so json.loads reports it where it starts.
                out.append(text[i:])
                break
            end += 2
            # Keep the comment's line breaks, so json.loads reports the file's line numbers.
            out.append("\n" * text.count("\n", i, end))
            i = end
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _parse(path: Path, text: Optional[str] = None) -> Dict[str, Any]:
    try:
        return json.loads(strip_comments(read_text(path) if text is None else text))
    except OSError as error:
        raise Invalid([Issue(str(path), f"can't read it: {error.strerror}")]) from error
    except UnicodeDecodeError as error:
        raise Invalid([Issue(str(path), f"not UTF-8 text at byte {error.start}")]) from error
    except json.JSONDecodeError as error:
        raise Invalid([Issue(str(path), f"not valid JSONC at line {error.lineno}, column {error.colno}: "
                                        f"{error.msg}")]) from error
    except (ValueError, RecursionError) as error:
        # The decoder's other failures: nesting too deep, or an integer too long to convert.
        raise Invalid([Issue(str(path), f"not valid JSONC: {error}")]) from error


def load_layers(user: Path = CONFIG, kit: Optional[Path] = None) -> List[Layer]:
    """The parsed layers in merge order, starting from the user's config. Without a config,
    a `global.md` beside where it would be is the user layer's `instructions`, as `addystack
    init` would name it: install moves the hosts' own text there before the first build."""
    kit = kit or _KIT
    defaults = Layer("defaults", kit, _parse(kit / "addystack.defaults.jsonc"))
    user = user.expanduser().absolute()
    if not (user.exists() or _is_file(user)):
        # A link whose file is gone is a config that's there but unreadable, not none.
        if user.is_symlink():
            raise Invalid([Issue(str(user), f"links to {os.readlink(user)}, which doesn't exist")])
        if _is_file(user.parent / GLOBAL):
            return [defaults, Layer("user", user.parent, {"instructions": GLOBAL})]
        return [defaults]
    return [defaults, Layer("user", user.parent, _parse(user))]


def _schema() -> Dict[str, Any]:
    return json.loads((_KIT / "schema" / "v1.json").read_text())


def _dotted(path: List[Any]) -> str:
    return ".".join(str(part) for part in path) or "(top level)"


def _check(value: Any, node: Dict[str, Any], path: List[Any], root: Dict[str, Any]) -> Iterator[Issue]:
    """Each issue with value against the schema node, at its dotted path."""
    unknown = set(node) - _ASSERTIONS - _ANNOTATIONS
    if unknown:
        raise ValueError(f"schema/v1.json uses keywords validate() doesn't evaluate: {sorted(unknown)}")
    if "$ref" in node:
        target: Any = root
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        yield from _check(value, target, path, root)
    if "const" in node and not _same(value, node["const"]):
        yield Issue(_dotted(path), f"must be {json.dumps(node['const'])}")
        return
    if "enum" in node and not any(_same(value, option) for option in node["enum"]):
        yield Issue(_dotted(path), f"{json.dumps(value)} is not one of {', '.join(map(str, node['enum']))}")
        return
    if "type" in node:
        allowed = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(isinstance(value, _TYPES[kind]) and (kind == "boolean" or not isinstance(value, bool))
                   for kind in allowed):
            yield Issue(_dotted(path), f"expected {' or '.join(allowed)}, got {_kind(value)}")
            return
    if isinstance(value, dict):
        properties = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                yield Issue(_dotted([*path, key]), "missing")
        if len(value) < node.get("minProperties", 0):
            yield Issue(_dotted(path), f"needs at least {node['minProperties']} key")
        for key, item in value.items():
            if key in properties:
                yield from _check(item, properties[key], [*path, key], root)
            elif node.get("additionalProperties") is False:
                known = ", ".join(properties)
                yield Issue(_dotted([*path, key]), f"unknown key; expected one of {known}")
    if isinstance(value, list) and "items" in node:
        for index, item in enumerate(value):
            yield from _check(item, node["items"], [*path, index], root)


def _same(value: Any, other: Any) -> bool:
    """Whether value equals other as JSON does, so true isn't 1."""
    return _kind(value) == _kind(other) and value == other


def _kind(value: Any) -> str:
    for kind, cls in _TYPES.items():
        if isinstance(value, cls) and (kind == "boolean" or not isinstance(value, bool)):
            return kind
    return "number"


def _bad_remotes(data: Any) -> List[Issue]:
    """An issue for each repo rule whose `remote` isn't a regex Python compiles."""
    policy = data.get("policy") if isinstance(data, dict) else None
    rules = policy.get("repos") if isinstance(policy, dict) else None
    issues = []
    for index, rule in enumerate(rules if isinstance(rules, list) else []):
        match = rule.get("match") if isinstance(rule, dict) else None
        remote = match.get("remote") if isinstance(match, dict) else None
        if isinstance(remote, str):
            try:
                re.compile(remote)
            except re.error as error:
                issues.append(Issue(f"policy.repos.{index}.match.remote", f"not a valid regex: {error}"))
    return issues


def _named_files(data: Any) -> Iterator[Tuple[str, str]]:
    """(dotted key, path) for each file a layer's data names: reply rules, taste,
    instructions, and lens files."""
    if not isinstance(data, dict):
        return
    sections = {"replies": ("rules",), "judgment": ("taste",)}
    for section, keys in sections.items():
        values = data.get(section)
        for key in keys:
            if isinstance(values, dict) and isinstance(values.get(key), str):
                yield f"{section}.{key}", values[key]
    if isinstance(data.get("instructions"), str):
        yield "instructions", data["instructions"]
    policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    places = [("policy.defaults", policy.get("defaults"))]
    places += [(f"policy.repos.{index}", rule) for index, rule in enumerate(policy.get("repos") or [])]
    for where, fields in places:
        lenses = fields.get("lenses") if isinstance(fields, dict) else None
        for index, lens in enumerate(lenses if isinstance(lenses, list) else []):
            if isinstance(lens, str) and _is_file_lens(lens):
                yield f"{where}.lenses.{index}", lens


def _missing_files(layer: Layer) -> List[Issue]:
    """An issue for each file the layer names that isn't there or can't be read."""
    issues = []
    for key, name in _named_files(layer.data):
        path = _absolute(name, layer.dir)
        if not _is_file(Path(path)):
            issues.append(Issue(key, f"no file at {path}"))
        elif os.path.abspath(path) not in _PLANNED and not os.access(path, os.R_OK):
            issues.append(Issue(key, f"can't read {path}"))
    return issues


# Keys a config may still hold from an earlier kit, with what to do instead. The schema
# doesn't know them, so each replaces its generic unknown-key issue.
_REMOVED = {
    "extends": Issue("extends", "removed: the kit ships no presets. Put each preset rule first in "
                                "policy.repos[], since preset rules applied before yours; write each file "
                                "path in them, such as a lens, relative to this config or absolute; then "
                                "delete extends"),
    "skills": Issue("skills", "removed: addystack doesn't choose skills. Install one with npx skills add <source> "
                              "--skill <name> -g, remove one with npx skills remove <name> -g, then delete skills"),
}


def validate(layers: List[Layer]) -> List[Issue]:
    """Each layer checked against schema/v1.json; empty when all are valid."""
    schema = _schema()
    issues: List[Issue] = []
    for layer in layers:
        where = "" if layer.name == "user" else f" (in {layer.name})"
        found = [_REMOVED.get(issue.path, issue) for issue in _check(layer.data, schema, [], schema)]
        found += _bad_remotes(layer.data)
        # Only a schema-valid layer's files are looked up, so a wrong type reports once.
        if not found:
            found += _missing_files(layer)
        issues += [Issue(issue.path, issue.message + where) for issue in found]
    return issues


def _absolute(value: Optional[str], folder: Path) -> Optional[str]:
    """value as an absolute path against folder, with `~` expanded; None stays None."""
    if value is None:
        return None
    return os.path.abspath(folder / Path(value).expanduser())


def _is_file_lens(lens: str) -> bool:
    """A lens holding a `/` or ending `.md` names a file; any other names a skill."""
    return "/" in lens or lens.endswith(".md")


def _lenses(lenses: List[str], folder: Path) -> List[str]:
    return [_absolute(lens, folder) if _is_file_lens(lens) else lens for lens in lenses]


def _fields(data: Dict[str, Any], folder: Path) -> Dict[str, Any]:
    """The policy fields data sets, with lens files made absolute."""
    fields = {key: data[key] for key in _POLICY_FIELDS if key in data}
    if "lenses" in fields:
        fields["lenses"] = _lenses(fields["lenses"], folder)
    return fields


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _toggle(state: Dict[str, List[str]], section: Dict[str, Any]) -> None:
    """Applies a layer's enable and disable lists to state's, as set operations."""
    for name in section.get("enable", []):
        state["disable"] = [n for n in state["disable"] if n != name]
        state["enable"] = [n for n in state["enable"] if n != name] + [name]
    for name in section.get("disable", []):
        state["enable"] = [n for n in state["enable"] if n != name]
        state["disable"] = [n for n in state["disable"] if n != name] + [name]


def _strictness(policy: Dict[str, Any]) -> tuple:
    return tuple(_RANK[field][policy[field]] for field in ("trust", "planning", "pushVia"))


def _unresolved(defaults: Dict[str, Any], rules: List[Rule]) -> Dict[str, Any]:
    """The strictest value of each policy field across the defaults and every rule."""
    effective = [defaults, *(_deep_merge(defaults, rule["set"]) for rule in rules)]
    strictest = dict(defaults)
    for field, rank in _RANK.items():
        strictest[field] = max((policy[field] for policy in effective), key=rank.__getitem__)
    strictest["decisionsSection"] = any(policy["decisionsSection"] for policy in effective)
    strictest["lenses"] = list(dict.fromkeys(lens for policy in effective for lens in policy["lenses"]))
    ranked = sorted(rules, key=lambda rule: _strictness(_deep_merge(defaults, rule["set"])), reverse=True)
    for field in ("issues", "verifySkill"):
        setter = next((rule for rule in ranked if field in rule["set"]), None)
        if setter is not None:
            strictest[field] = setter["set"][field]
    return strictest


def _digest(layers: List[Layer], files: List[Optional[str]]) -> str:
    """A hash of every layer's data and the text of each file the config names."""
    digest = hashlib.sha256(json.dumps([[layer.name, layer.data] for layer in layers],
                                       sort_keys=True).encode())
    for name in files:
        path = Path(name) if name else None
        digest.update(read_text(path).encode() if path and os.path.abspath(path) in _PLANNED
                      else path.read_bytes() if path and path.is_file() else b"\0")
    return digest.hexdigest()


def merge(layers: List[Layer], kit: Path) -> Resolved:
    """The layers merged by the rules in this module's docstring."""
    plain: Dict[str, Any] = {}
    defaults: Dict[str, Any] = {}
    rules: List[Rule] = []
    exclude: List[str] = []
    instructions: List[str] = []
    hooks = {"enable": [], "disable": []}
    for layer in layers:
        data = layer.data
        replies = dict(data.get("replies", {}))
        if "rules" in replies:
            replies["rules"] = _absolute(replies["rules"], layer.dir)
        judgment = json.loads(json.dumps(data.get("judgment", {})))
        if "taste" in judgment:
            judgment["taste"] = _absolute(judgment["taste"], layer.dir)
        exclude += judgment.get("principles", {}).pop("exclude", [])
        plain = _deep_merge(plain, {
            "identity": data.get("identity", {}),
            "hosts": data.get("hosts", {}),
            "replies": replies,
            "judgment": judgment,
            "hooks": {key: value for key, value in data.get("hooks", {}).items() if key == "preset"},
        })
        policy = data.get("policy", {})
        defaults = _deep_merge(defaults, _fields(policy.get("defaults", {}), layer.dir))
        for index, rule in enumerate(policy.get("repos", [])):
            match = {key: (os.path.expanduser(value) if key == "path" else value)
                     for key, value in rule["match"].items()}
            rules.append({"match": match, "set": _fields(rule, layer.dir), "source": f"{layer.name}#{index}"})
        if data.get("instructions"):
            instructions.append(_absolute(data["instructions"], layer.dir))
        _toggle(hooks, data.get("hooks", {}))
    plain["judgment"].setdefault("principles", {})["exclude"] = list(dict.fromkeys(exclude))
    files = [plain["replies"].get("rules"), plain["judgment"].get("taste"), *instructions]
    return {
        "version": 1,
        "kit": str(kit.resolve()),
        "layers": [layer.name for layer in layers],
        "digest": _digest(layers, files),
        "identity": plain["identity"],
        "hosts": plain["hosts"],
        "replies": plain["replies"],
        "policy": {"defaults": defaults, "unresolved": _unresolved(defaults, rules), "rules": rules},
        "judgment": plain["judgment"],
        "instructions": instructions,
        "hooks": {**plain["hooks"], **hooks},
    }


REPO_FIELDS = ("planning", "trust", "pushVia")


def load_repo_policy(path: Path) -> Dict[str, Any]:
    """A repo's `.agents/addystack.jsonc`, parsed and checked against schema/v1.json's
    `repoPolicy`: only `planning`, `trust`, and `pushVia`. Raises Invalid with every
    issue, the file's path included, when it can't be read, isn't JSONC, or fails the
    schema."""
    data = _parse(path, _read_repo_file(path))
    schema = _schema()
    issues = list(_check(data, schema["definitions"]["repoPolicy"], [], schema))
    if issues:
        raise Invalid([Issue(issue.path, f"{issue.message} (in {path})") for issue in issues])
    return {key: data[key] for key in REPO_FIELDS if key in data}


# A repo policy is a few lines; anything longer isn't one.
_REPO_FILE_LIMIT = 64 * 1024


def _read_repo_file(path: Path) -> str:
    """A repo policy file's text. The repo controls the path, so only a regular file of
    at most _REPO_FILE_LIMIT bytes is read: a FIFO or device would hang the hook."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise Invalid([Issue(str(path), "not a regular file")])
        with open(path, "rb") as file:
            data = file.read(_REPO_FILE_LIMIT + 1)
    except OSError as error:
        raise Invalid([Issue(str(path), f"can't read it: {error.strerror}")]) from error
    if len(data) > _REPO_FILE_LIMIT:
        raise Invalid([Issue(str(path), f"over {_REPO_FILE_LIMIT // 1024} KiB")])
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Invalid([Issue(str(path), f"not UTF-8 text at byte {error.start}")]) from error


def stricter(field: str, one: str, other: str) -> str:
    """The stricter of two values of a REPO_FIELDS field, by the order policy.unresolved
    uses: gated over autonomous, draft over merge-on-go over gate, gh-stack over git."""
    rank = _RANK[field]
    return one if rank[one] >= rank[other] else other


def resolve(user: Path = CONFIG, kit: Optional[Path] = None) -> Resolved:
    """load_layers, validate, and merge; raises Invalid with every issue found."""
    layers = load_layers(user, kit)
    issues = validate(layers)
    if issues:
        raise Invalid(issues)
    return merge(layers, kit or _KIT)

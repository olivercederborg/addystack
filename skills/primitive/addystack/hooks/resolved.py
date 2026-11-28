"""The resolved addystack config, as hooks and the `addystack policy` command read it.

`addystack build` merges the kit's defaults and the user's own preferences into
~/.local/state/addystack/resolved.json. This module is the only part of addystack a hook
imports to read it: hooks ask for a checkout's policy, the reply preferences, or the
kit's path, and never see layers, JSONC, or match rules.

    import resolved
    if any(resolved.policy(d).pushVia == "gh-stack" for d in dirs):
        deny()

A checkout's policy starts from `policy.defaults`, and each `policy.repos` rule that
matches it sets its own fields over that, in layer order, so a later rule wins field by
field. A checkout whose remote can't be read gets `policy.unresolved`, which build sets to
the strictest value of each field across every rule, so a lookup failure never loosens
what a hook enforces. Not a repo, or a repo with no remotes, gets the defaults. A missing
or unreadable resolved.json, or one with a field of the wrong type or value, gives the
kit's defaults, and `addystack doctor` fails.

A repo can commit its own policy in `.agents/addystack.jsonc` at its top level, read at
call time and checked against schema/v1.json's `repoPolicy`. It holds only `planning`,
`trust`, and `pushVia`, which it can only make stricter: each takes the stricter of the
repo's value and the user's, by the order policy.unresolved uses, so a cloned repo can't
grant itself merging. It may also name the repo's review App in `review`, which applies
when the user's config names none and no matching rule sets `review`, so a rule's
`"review": null` turns the repo's App off. A file that applied adds `repo-file` to `matched`. One
that can't be read, isn't JSONC, or fails the schema gives the checkout
policy.unresolved, with `repo-file-invalid` in `matched`.

A rule's `remote` is searched in the origin URL, so it never matches a repo with no
remotes, while its `path` glob still can. Git runs with LC_ALL=C and no network access.
`check_queue()` reads the agent memory guard's check queue settings, and falls back to the
kit's for that section alone, so a resolved.json built before the section existed keeps
its policy.

`ADDYSTACK_STATE` overrides the state folder that holds resolved.json, for tests and dry
runs.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from os import PathLike
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Set, Tuple, get_args

Planning = Literal["gated", "autonomous"]
Trust = Literal["draft", "gate", "merge-on-go"]
PushVia = Literal["git", "gh-stack"]
Issues = Literal["none", "github", "linear"]
ReplyStyle = Literal["reply-shape", "own"]
Next = Literal["off", "lettered"]

STATE = Path(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")) / "resolved.json"
# A repo's own policy file, relative to its top level.
REPO_FILE = Path(".agents") / "addystack.jsonc"


@dataclass(frozen=True)
class Review:
    """The GitHub App that reviews every ready PR, by its slug, when its approval is the
    one the repo requires."""
    app: str


@dataclass(frozen=True)
class Policy:
    """How agents work in one checkout. `matched` names the rules that set it, such as
    `user#0`, then `repo-file` when the repo's own policy file applied; or
    it holds `unresolved` when the remote couldn't be read, and `unresolved` and
    `repo-file-invalid` when the repo's file couldn't be used."""
    planning: Planning
    trust: Trust
    pushVia: PushVia
    issues: Issues
    lenses: tuple[str, ...]
    verifySkill: Optional[str]
    decisionsSection: bool
    review: Optional[Review]
    matched: tuple[str, ...]


@dataclass(frozen=True)
class Replies:
    """The user's reply preferences. `rules` is the absolute path of their reply rules
    file, or None when they keep their own rules in their instructions."""
    style: ReplyStyle
    rules: Optional[Path]
    next: Next
    turnBlock: bool


@dataclass(frozen=True)
class CheckQueue:
    """The agent memory guard's check queue: whether it runs, how many busy heavy checks
    run at once, and the cores running checks may use before a new one waits."""
    enabled: bool
    maxChecks: int
    maxCores: int


_KIT = Path(__file__).resolve().parent.parent


def _config() -> Any:
    """lib/config.py, imported only when a lookup needs it, so most hook runs skip it."""
    lib = str(_KIT / "lib")
    # First on the path, so a project's own config.py on PYTHONPATH can't stand in for it.
    if sys.path[:1] != [lib]:
        sys.path.insert(0, lib)
    import config
    return config


def _kit_defaults() -> Dict[str, Any]:
    """The Resolved value of the kit's defaults alone, from lib/config.py."""
    config = _config()
    # A user config that can't exist, so only the kit's defaults load.
    return config.merge(config.load_layers(Path(os.devnull) / "none"), _KIT)


def _state() -> Dict[str, Any]:
    """resolved.json, or the kit's defaults when it's missing or unreadable, or when any
    field policy(), replies(), or kit() reads is absent, of the wrong type, or not an
    allowed value. The whole file falls back at once, so the three never mix sources."""
    try:
        data = json.loads(STATE.expanduser().read_text())
        _read_all(data)
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return _kit_defaults()


def _read_all(data: Any) -> None:
    """Reads every field the accessors read, raising on the first one they couldn't."""
    table = data["policy"]
    _make_policy(table["defaults"], ())
    _make_policy(table["unresolved"], ())
    for rule in _typed(table["rules"], list):
        for value in _typed(rule["match"], dict).values():
            _typed(value, str)
        _make_policy({**table["defaults"], **_typed(rule["set"], dict)}, (_typed(rule["source"], str),))
    _replies(data)
    _typed(data["kit"], str)


def _one_of(value: Any, kind: Any) -> Any:
    """value, when it's one of the Literal kind's values; ValueError otherwise."""
    if not isinstance(value, str) or value not in get_args(kind):
        raise ValueError(f"{value!r} isn't one of {get_args(kind)}")
    return value


def _typed(value: Any, *kinds: type) -> Any:
    """value, when it's one of kinds; TypeError otherwise."""
    if not isinstance(value, kinds):
        raise TypeError(f"{value!r} isn't a {kinds}")
    return value


def _git(checkout: str | PathLike[str], *args: str) -> subprocess.CompletedProcess[str]:
    # surrogateescape keeps a path's bytes that aren't UTF-8, as Linux allows.
    return subprocess.run(["git", "-C", os.fspath(checkout), *args], capture_output=True, text=True,
                          errors="surrogateescape", env={**os.environ, "LC_ALL": "C"})


def _make_policy(fields: Dict[str, Any], matched: Tuple[str, ...]) -> Policy:
    lenses = _typed(fields["lenses"], list)
    return Policy(planning=_one_of(fields["planning"], Planning), trust=_one_of(fields["trust"], Trust),
                  pushVia=_one_of(fields["pushVia"], PushVia), issues=_one_of(fields["issues"], Issues),
                  lenses=tuple(_typed(lens, str) for lens in lenses),
                  verifySkill=_typed(fields["verifySkill"], str, type(None)),
                  decisionsSection=_typed(fields["decisionsSection"], bool),
                  review=_review(fields.get("review")), matched=matched)


def _review(value: Any) -> Optional[Review]:
    """The review App a policy field names, or None. A resolved.json built before the
    field existed has none, so it reads as None."""
    if value is None:
        return None
    return Review(app=_typed(_typed(value, dict)["app"], str))


def _matches(match: Dict[str, str], origin: Optional[str], roots: Set[str]) -> bool:
    if "remote" in match and (origin is None or not re.search(match["remote"], origin, re.I)):
        return False
    if "path" in match:
        globs = {match["path"], _real_glob(match["path"])}
        return any(fnmatch.fnmatchcase(root, glob) for root in roots for glob in globs)
    return True


def _roots(checkout: str | PathLike[str], top: str) -> Set[str]:
    """The checkout's root as git reports it, with links resolved, and as reached
    through the path the caller gave, so a glob whose wildcard covers a link still
    matches."""
    real = os.path.realpath(top)
    roots = {top, real}
    here = os.path.abspath(checkout)
    while True:
        if os.path.realpath(here) == real:
            roots.add(here)
            return roots
        parent = os.path.dirname(here)
        if parent == here:
            return roots
        here = parent


def _real_glob(glob: str) -> str:
    """glob with its leading folders, up to the first wildcard, resolved through links,
    so a rule naming a linked folder matches the checkout git reports."""
    parts = glob.split(os.sep)
    fixed = next((i for i, part in enumerate(parts) if any(c in part for c in "*?[")), len(parts))
    prefix = os.sep.join(parts[:fixed]) or os.sep
    return os.path.join(os.path.realpath(prefix), *parts[fixed:])


def policy(checkout: str | PathLike[str]) -> Policy:
    """The policy for the checkout at `checkout`, from its origin remote and path. Any
    error past reading the state, such as a git path that won't decode or a repo file the
    JSON decoder chokes on, gives policy.unresolved: a hook that crashes enforces nothing,
    so a lookup failure fails closed."""
    table = _state()["policy"]
    try:
        return _policy(table, checkout)
    except Exception:
        return _make_policy(table["unresolved"], ("unresolved",))


def _policy(table: Dict[str, Any], checkout: str | PathLike[str]) -> Policy:
    unresolved = _make_policy(table["unresolved"], ("unresolved",))
    probe = _git(checkout, "rev-parse", "--git-dir")
    if probe.returncode != 0:
        if not os.path.isdir(checkout) or "not a git repository" in probe.stderr:
            return _make_policy(table["defaults"], ())
        return unresolved
    top = _toplevel(checkout)
    if top is None and _git(checkout, "rev-parse", "--is-bare-repository").stdout.strip() != "true":
        # Inside a work tree's .git folder, git finds the repo but no top level, so the
        # repo's own file can't be read: fail closed rather than skip it.
        return unresolved
    user = _user_policy(table, checkout, top, unresolved)
    rule_sets_review = any("review" in rule["set"] for rule in table["rules"]
                           if rule["source"] in user.matched)
    return _with_repo_file(user, top, unresolved, keep_review=rule_sets_review)


def _toplevel(checkout: str | PathLike[str]) -> Optional[str]:
    """The checkout's top level, or None outside a work tree. Only git's closing newline
    is cut, since a folder's name can end in a space."""
    found = _git(checkout, "rev-parse", "--show-toplevel")
    return found.stdout[:-1] if found.returncode == 0 and found.stdout.endswith("\n") else None


def _user_policy(table: Dict[str, Any], checkout: str | PathLike[str], top: Optional[str],
                 unresolved: Policy) -> Policy:
    """The checkout's policy from the user's config alone: the defaults, then each
    matching rule's fields, or unresolved when the origin can't be read."""
    origin: Optional[str] = None
    remotes = _git(checkout, "remote")
    if remotes.returncode != 0 or remotes.stdout.split():
        found = _git(checkout, "remote", "get-url", "origin")
        if found.returncode != 0:
            return unresolved
        origin = found.stdout.strip()
    roots = _roots(checkout, top) if top is not None else set()
    fields, matched = dict(table["defaults"]), []
    for rule in table["rules"]:
        try:
            hit = _matches(rule["match"], origin, roots)
        except re.error:
            return unresolved
        if hit:
            fields.update(rule["set"])
            matched.append(rule["source"])
    return _make_policy(fields, tuple(matched))


def _with_repo_file(policy: Policy, top: Optional[str], unresolved: Policy, keep_review: bool) -> Policy:
    """policy with each field the repo's own file sets made the stricter of the two, and
    the file's review App when policy has none and keep_review is false, or unresolved
    when the file is there but can't be used."""
    if top is None:
        return policy
    path = Path(top) / REPO_FILE
    invalid = replace(unresolved, matched=("unresolved", "repo-file-invalid"))
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        # Absent only when .agents is missing or a real folder: a dangling .agents link
        # hides whatever file it pointed to.
        folder = path.parent
        if os.path.lexists(folder) and not os.path.isdir(folder):
            return invalid
        return policy
    except OSError:
        # Present but unreachable, such as a .agents folder that can't be searched.
        return invalid
    config = _config()
    try:
        repo = config.load_repo_policy(path)
    except config.Invalid:
        return invalid
    fields: Dict[str, Any] = {field: config.stricter(field, repo[field], getattr(policy, field))
                              for field in config.REPO_FIELDS if field in repo}
    if repo.get("review") is not None and policy.review is None and not keep_review:
        fields["review"] = _review(repo["review"])
    return replace(policy, **fields, matched=(*policy.matched, "repo-file"))


def replies() -> Replies:
    """The user's reply preferences."""
    return _replies(_state())


def _replies(state: Dict[str, Any]) -> Replies:
    data = state["replies"]
    rules = _typed(data["rules"], str, type(None))
    return Replies(style=_one_of(data["style"], ReplyStyle), rules=Path(rules) if rules else None,
                   next=_one_of(data["next"], Next), turnBlock=_typed(data["turnBlock"], bool))


def check_queue() -> CheckQueue:
    """The check queue's settings. A resolved.json built before the section existed, or
    with a bad value in it, gives the kit's defaults for this section alone; policy(),
    replies(), and kit() still read the file."""
    try:
        return _check_queue(_state()["checkQueue"])
    except (KeyError, TypeError, ValueError):
        return _check_queue(_kit_defaults()["checkQueue"])


def _check_queue(data: Any) -> CheckQueue:
    return CheckQueue(enabled=_typed(data["enabled"], bool), maxChecks=_count(data["maxChecks"]),
                      maxCores=_count(data["maxCores"]))


def _count(value: Any) -> int:
    """value, when it's an integer of at least 1 and not a boolean; ValueError otherwise."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{value!r} isn't a count")
    return value


def kit() -> Path:
    """The absolute path of the kit, the addystack skill's folder, for code outside it,
    such as a skill in the user's preferences, that imports a public kit module like
    turn_block."""
    return Path(_state()["kit"])

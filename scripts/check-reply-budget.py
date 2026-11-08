#!/usr/bin/env python3
"""Fails when a reply-rules payload passes 8,000 characters.

hooks/reply-shape-context.py injects reply-shape's SKILL.md, and in a second SessionStart
entry the user's rules file, as two separate payloads. Past 10,000 characters Claude Code
loads only a 2,000-character preview, so 8,000 keeps a margin. Each payload is checked on
its own, built by the hook's own `context()`:

- reply-shape: this checkout's skills/optional/reply-shape/SKILL.md, and the one the hook loads
  (REPLY_SHAPE_SKILL, or the installed skill) when that's another file.
- rules: the checkout's replies.md when it has one (the workshop's maintainer does), so a
  commit that grows it fails here, and the file
  `replies.rules` names in the built resolved.json (ADDYSTACK_STATE overrides its folder)
  when that's another file.

A payload that couldn't load fails too.

Usage: scripts/check-reply-budget.py   # print each size; exit 1 when one is over
"""

import importlib.util
import pathlib
import sys

LIMIT = 8_000
ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "skills" / "primitive" / "addystack" / "hooks"


def hook():
    """hooks/reply-shape-context.py as a module."""
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("reply_shape_context", HOOKS / "reply-shape-context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_rules():
    """The rules file the built config names, or None without a build or a rules file."""
    import resolved
    if resolved.STATE.expanduser().is_file():
        return resolved.replies().rules
    return None


def payloads(module):
    """Each (name, path) to check: this checkout's copies, which must load, then each
    other file the hook would load instead, once per real file. One of those that's
    missing is skipped: the hook warns about it, and doctor reports a missing rules file."""
    own = [("reply-shape", ROOT / "skills" / "optional" / "reply-shape" / "SKILL.md")]
    own += [("rules", ROOT / "replies.md")] if (ROOT / "replies.md").is_file() else []
    others = [("reply-shape", module.skill_path()), ("rules", configured_rules())]
    candidates = own + [(name, path) for name, path in others if path is not None and pathlib.Path(path).exists()]
    seen, out = set(), []
    for name, path in candidates:
        key = str(pathlib.Path(path).resolve()) if pathlib.Path(path).exists() else str(path)
        if key not in seen:
            seen.add(key)
            out.append((name, pathlib.Path(path)))
    return out


def main():
    module = hook()
    context = module.context
    status = 0
    for name, path in payloads(module):
        try:
            size = len(context(path))
        except OSError as error:
            print(f"{name}: couldn't load {path} ({error.strerror})", file=sys.stderr)
            status = 1
            continue
        print(f"{name}: {size:,} of {LIMIT:,} characters ({path})")
        if size > LIMIT:
            print(f"{name}: over the budget; cut or disclose rules to get under {LIMIT:,}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())

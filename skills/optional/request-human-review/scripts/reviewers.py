"""request-human-review's reader of a repository's `.github/REVIEWERS`, and its pick of whom
to ask about a PR's gated decisions. Pure: no GitHub, no files; handoff.py reads them.

REVIEWERS uses CODEOWNERS syntax in `## <domain>` blocks. A pattern's names are the domain's
P1, then an optional P2 (a P3 counts as listed, never as covering). The last pattern that
matches a path wins. `## <domain> · pinned` names the domain `<domain>`. The `unowned` block
lists patterns that belong to no domain, such as an ADR, which belongs to the PR's main
change instead. A domain may list nobody.

    rule     = {'pattern': '/packages/billing/', 'domain': 'billing', 'names': ['alice', 'bob'], 'match': fullmatch}
    placed   = {**decision, 'domain': 'billing' | None}            None: no domain, the fallback
    reviewer = {'login': 'alice', 'role': 'P1' | 'P2' | 'fallback', 'domains': ['billing']}
"""
from __future__ import annotations

import re

PATH = '.github/REVIEWERS'
UNOWNED = 'unowned'


def parse(text: str) -> list:
    """The file's rules in order, refused with every line it can't read named."""
    rules, problems, current = [], [], None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith('## '):
            current = line[3:].split(' · ')[0].strip()
            continue
        if not line or line.startswith('#'):
            continue
        # A ` #` starts an inline comment, as in CODEOWNERS.
        pattern, *names = line.split(' #', 1)[0].split()
        if current is None:
            problems.append(f'line {number}: {pattern} comes before any `## <domain>` heading')
        elif current == UNOWNED and names:
            problems.append(f'line {number}: the {UNOWNED} block names nobody, but {pattern} names {" ".join(names)}')
        elif bad := [name for name in names if not re.fullmatch(r'@[A-Za-z0-9-]+', name)]:
            problems.append(f'line {number}: {" ".join(bad)} is not an @login')
        else:
            rules.append({'pattern': pattern, 'domain': current, 'names': [name[1:] for name in names],
                          'match': _matcher(pattern)})
    if problems:
        raise ValueError('REVIEWERS: ' + '; '.join(problems))
    return rules


def _matcher(pattern: str):
    """CODEOWNERS' rules: a pattern with a slash before its end is anchored at the root, one
    without matches at any depth, a trailing slash matches only a directory's contents, `*` and
    `?` stay within one path segment, `**` crosses them, and a pattern ending `/*` matches only
    the files directly in that directory."""
    anchored = '/' in pattern.rstrip('/')
    body = pattern.strip('/')
    expression = ''
    for token in re.split(r'(/\*\*/|\*\*/|/\*\*|\*\*|\*|\?)', body):
        expression += {'/**/': '/(?:.*/)?', '**/': '(?:.*/)?', '/**': '/.*', '**': '.*', '*': '[^/]*',
                       '?': '[^/]'}.get(token, re.escape(token))
    tail = '/.*' if pattern.endswith('/') else '' if pattern.endswith('/*') else '(?:/.*)?'
    return re.compile(('' if anchored else '(?:.*/)?') + expression + tail).fullmatch


def domain(rules: list, path: str) -> str | None:
    """The domain of the last rule matching path, or None when none matches or it's unowned."""
    found = next((rule['domain'] for rule in reversed(rules) if rule['match'](path.lstrip('/'))), None)
    return None if found == UNOWNED else found


def names(rules: list, of: str) -> list:
    """A domain's logins in priority order, across all its patterns."""
    return list(dict.fromkeys(name for rule in rules if rule['domain'] == of for name in rule['names']))


def file_of(code: str) -> str:
    """The file in a `path:line` or `path:start-end` anchor."""
    return re.sub(r':\d+(?:-\d+)?$', '', code or '')


def place(rules: list, decisions: list, changed: list) -> list:
    """Each decision with its domain: the last match for the path in its `code`; one in no
    domain or in `unowned`, or without a path, takes the PR's main change's, the domain with the
    most of the changed files; None when no changed file is in a domain either."""
    counts = {}
    for path in changed:
        if found := domain(rules, path):
            counts[found] = counts.get(found, 0) + 1
    main = min(counts, key=lambda name: (-counts[name], name)) if counts else None
    return [{**decision, 'domain': (file_of(decision.get('code', '')) and domain(rules, file_of(decision['code']))) or main}
            for decision in decisions]


def pick(rules: list, placed: list, author: str, engaged: list, load: dict) -> list:
    """The reviewers to request, from domains with the most decisions to the fewest. A domain
    an engaged or already picked login covers, as its P1 or P2, adds nobody; otherwise its
    P1, or its P2 when the P1 is the author. A domain that is None or lists nobody but the
    author is covered by anyone engaged or picked, and otherwise takes the fallback: everyone
    the file names but the author, with the fewest open requests in `load`, then by name."""
    counts = {}
    for decision in placed:
        counts[decision['domain']] = counts.get(decision['domain'], 0) + 1
    # Named domains first, so a person picked for one can cover a domain with nobody.
    order = sorted(counts, key=lambda name: (name is None, -counts[name], name or ''))
    picked = []
    for name in order:
        asked = list(engaged) + [reviewer['login'] for reviewer in picked]
        priority = names(rules, name)[:2] if name else []
        if covering := [reviewer for reviewer in picked if reviewer['login'] in priority]:
            covering[0]['domains'].append(name)
            continue
        if any(login in priority for login in asked):
            continue
        if candidates := [login for login in priority if login != author]:
            role = 'P1' if candidates[0] == priority[0] else 'P2'
            picked.append({'login': candidates[0], 'role': role, 'domains': [name]})
            continue
        if asked:
            continue
        pool = [login for login in dict.fromkeys(n for rule in rules for n in rule['names']) if login != author]
        if pool:
            login = min(pool, key=lambda login: (load.get(login, 0), login.lower()))
            picked.append({'login': login, 'role': 'fallback', 'domains': [name] if name else []})
    return picked

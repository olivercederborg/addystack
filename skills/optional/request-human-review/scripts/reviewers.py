"""request-human-review's reader of a repository's `.github/REVIEWERS`, and its pick of whom
to ask about a PR's gated decisions. Pure: no GitHub, no files; handoff.py reads them.

REVIEWERS uses CODEOWNERS syntax in `## <domain>` blocks. The names belong to the domain, P1
first, then an optional P2 (a P3 counts as listed, never as covering): every pattern in a
domain lists the same people, and where they differ the domain takes them in file order. The last pattern that
matches a path wins. `## <domain> · pinned` names the domain `<domain>`. The `unowned` block
lists patterns that belong to no domain, such as an ADR, which belongs to the PR's main
change instead. A domain may list nobody.

The lines above the first domain hold the pick's settings, one `name: value` each:

    priority: 3 2 1          points for a domain's P1, P2 and P3; nobody else gets any
    open ask: 1              minus this for each review request they haven't started
    share: 10                minus this times how far their review share is above the lowest
    share since: 2026-12-01  review shares count from this date, at most 14 days back

    rule     = {'pattern': '/packages/billing/', 'domain': 'billing', 'names': ['alice', 'bob'], 'match': fullmatch}
    placed   = {**decision, 'domain': 'billing' | None}            None: no domain, the fallback
    reviewer = {'login': 'alice', 'role': 'P1' | 'P2' | 'fallback', 'domains': ['billing']}
"""
from __future__ import annotations

import datetime as dt
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
        # Lines above the first domain, such as comments or settings, aren't rules.
        if not line or line.startswith('#') or current is None:
            continue
        # A `#` after whitespace starts an inline comment, as in CODEOWNERS.
        # A backslash escapes a space in a pattern, as in gitignore.
        pattern, *names = re.findall(r'(?:\\.|\S)+', re.split(r'\s#', line, maxsplit=1)[0])
        pattern = pattern.replace('\\ ', ' ')
        if current == UNOWNED and names:
            problems.append(f'line {number}: the {UNOWNED} block names nobody, but {pattern} names {" ".join(names)}')
        elif bad := [name for name in names if not re.fullmatch(r'@[A-Za-z0-9-]+', name)]:
            problems.append(f'line {number}: {" ".join(bad)} is not an @login')
        else:
            rules.append({'pattern': pattern, 'domain': current, 'names': [name[1:] for name in names],
                          'match': _matcher(pattern)})
    if problems:
        raise ValueError('REVIEWERS: ' + '; '.join(problems))
    return rules


def settings(text: str) -> dict:
    """The pick's settings from the lines above the first domain:
    {'weights': {'P1', 'P2', 'P3', 'open ask', 'share'}, 'share_since': date}, refused with each
    line it can't read and each setting it lacks named."""
    found, problems = {}, []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith('## '):
            break
        if not line or line.startswith('#'):
            continue
        name, colon, value = (part.strip() for part in line.partition(':'))
        try:
            if not colon or name not in SETTINGS:
                raise ValueError
            found[name] = SETTINGS[name](value)
        except ValueError:
            problems.append(f'line {number}: {line}')
    problems += [f'no `{name}:` line above the first domain' for name in SETTINGS if name not in found]
    if problems:
        raise ValueError('REVIEWERS settings: ' + '; '.join(problems))
    first, second, third = found['priority']
    return {'weights': {'P1': first, 'P2': second, 'P3': third, 'open ask': found['open ask'], 'share': found['share']},
            'share_since': found['share since']}


def _priority(value: str) -> tuple:
    points = tuple(float(point) for point in value.split())
    if len(points) != 3:
        raise ValueError
    return points


SETTINGS = {'priority': _priority, 'open ask': float, 'share': float, 'share since': dt.date.fromisoformat}


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
    return unique(name for rule in rules if rule['domain'] == of for name in rule['names'])


def unique(logins) -> list:
    """Each login once, ignoring case, in its first spelling."""
    seen = {}
    for login in logins:
        seen.setdefault(login.lower(), login)
    return list(seen.values())


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


def has(logins, login: str) -> bool:
    """Whether login is among logins: GitHub logins ignore case, and REVIEWERS is typed by hand."""
    return login.lower() in {other.lower() for other in logins}


def pick(rules: list, placed: list, author: str, engaged: list, load: dict) -> list:
    """The reviewers to request, from domains with the most decisions to the fewest. A domain
    an engaged or already picked login covers, as its P1 or P2, adds nobody; otherwise its
    P1, or its P2 when the P1 is the author. A domain that is None or lists nobody but the
    author is covered by anyone engaged or picked, and otherwise takes the fallback: everyone
    the file names but the author, with the fewest open requests in `load`, then by name."""
    load = {login.lower(): count for login, count in load.items()}
    counts = {}
    for decision in placed:
        counts[decision['domain']] = counts.get(decision['domain'], 0) + 1
    # Domains with a P1 or P2 to ask first, so a person picked for one can cover a domain with nobody.
    def listed(name):
        return bool(name) and any(login.lower() != author.lower() for login in names(rules, name)[:2])
    order = sorted(counts, key=lambda name: (not listed(name), -counts[name], name or ''))
    picked = []
    for name in order:
        asked = list(engaged) + [reviewer['login'] for reviewer in picked]
        priority = names(rules, name)[:2] if name else []
        if covering := [reviewer for reviewer in picked if has(priority, reviewer['login'])]:
            covering[0]['domains'].append(name)
            continue
        if any(has(priority, login) for login in asked):
            continue
        if candidates := [login for login in priority if login.lower() != author.lower()]:
            role = 'P1' if candidates[0] == priority[0] else 'P2'
            picked.append({'login': candidates[0], 'role': role, 'domains': [name]})
            continue
        if asked:
            continue
        pool = [login for login in unique(n for rule in rules for n in rule['names']) if login.lower() != author.lower()]
        if pool:
            login = min(pool, key=lambda login: (load.get(login.lower(), 0), login.lower()))
            picked.append({'login': login, 'role': 'fallback', 'domains': [name] if name else []})
    return picked

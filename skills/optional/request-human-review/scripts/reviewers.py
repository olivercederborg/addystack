#!/usr/bin/env python3
"""request-human-review's reader of a repository's `.github/REVIEWERS`, and its pick of whom
to ask about a PR's gated decisions. Pure: no GitHub, no files; handoff.py reads them.

REVIEWERS uses CODEOWNERS syntax in `## <domain>` blocks. A pattern's names are the domain's
P1, then an optional P2 (a P3 counts as listed, never as covering). The last pattern that
matches a path wins. `## <domain> · pinned` names the domain `<domain>`. The `unowned` block
lists patterns that belong to no domain, such as an ADR, which belongs to the PR's main
change instead. A domain may list nobody.

    rule     = {'pattern': '/packages/billing/', 'domain': 'billing', 'names': ['alice', 'bob']}
    placed   = {**decision, 'domain': 'billing' | None}            None: no domain, the fallback
    reviewer = {'login': 'alice', 'role': 'P1' | 'P2' | 'fallback', 'domains': ['billing']}
"""
from __future__ import annotations

PATH = '.github/REVIEWERS'
UNOWNED = 'unowned'


def parse(text: str) -> list:
    """The file's rules in order, refused with every line it can't read named."""
    raise NotImplementedError


def domain(rules: list, path: str) -> str | None:
    """The domain of the last rule matching path, or None when none matches or it's unowned."""
    raise NotImplementedError


def place(rules: list, decisions: list, changed: list) -> list:
    """Each decision with its domain: the last match for the path in its `code`; one in no
    domain or in `unowned`, or without a path, takes the PR's main change's, the domain with the
    most of the changed files; None when no changed file is in a domain either."""
    raise NotImplementedError


def pick(rules: list, placed: list, author: str, engaged: list, load: dict) -> list:
    """The reviewers to request, from domains with the most decisions to the fewest. A domain
    an engaged or already picked login covers, as its P1 or P2, adds nobody; otherwise its
    P1, or its P2 when the P1 is the author. A domain that is None or lists nobody but the
    author is covered by anyone engaged or picked, and otherwise takes the fallback: everyone
    the file names but the author, with the fewest open requests in `load`, then by name."""
    raise NotImplementedError

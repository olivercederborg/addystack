#!/usr/bin/env python3
"""request-human-review's handoff: when a PR needs a human, one PR comment that hands the
gated decisions to whoever reviews them, then a review request to the people REVIEWERS
names. The comment is written for the agent that runs the human's review: a one-line header
for people glancing at the PR, every decision in full, and a versioned block that `read`
parses. It names whom it requested without an @mention, since the request notifies them.

Frankie's unattended review hands off through post-review.py once its needs-human review
posted. A PR's author runs it with their go, and may name the reviewer:

    handoff.py N GATES.json [--reviewer LOGIN]... [--with-suggested]   print the draft
    handoff.py N GATES.json [--reviewer LOGIN]... [--with-suggested] --disclosure LINE --send

`--send` posts the comment, then requests. It never requests the PR's author. A handoff of
the same decisions as the signed-in login's own last one posts no comment, and requests only
the reviewers that handoff named who are no longer requested and haven't reviewed, so a run
that commented and then failed to request finishes on a retry.

The block, the comment's last lines; a field added later keeps v1, a renamed or removed one
is v2, and a reader takes the last block it trusts:

    <!-- addystack-handoff:v1
    {"pr", "base", "head", "by", "chosen_by": "rule" | "author", "second_opinion": why | null,
     "decisions": [{"key", "id", "gate", "decision", "ask", "why", "code", "domain"}],
     "reviewers": [{"login", "role", "domains"}], "engaged": [login]}
    -->
"""
from __future__ import annotations

import re

MARK, VERSION = 'addystack-handoff', 1
SECOND_OPINION = 'second-opinion'
BLOCK = re.compile(rf'<!-- {MARK}:v(\d+)\n(.*?)\n-->', re.S)


def github(*arguments) -> str:
    """github.sh with these arguments, its stdout, or ValueError with its error."""
    raise NotImplementedError


def key(decision: dict) -> str:
    """A decision's identity across reviews: its Decisions-table id, or the path in its `code`
    when it has none, with its gate. Wording and line numbers change between reviews."""
    raise NotImplementedError


def plan(number: int, verdict: dict, disclosure: str, no_second_opinion: str | None = None,
         chosen: tuple = (), with_suggested: bool = False) -> dict:
    """What a handoff would post, from reads only:
    {'post': bool, 'why', 'head', 'decisions': [placed], 'request': [reviewer],
     'suggested': [reviewer], 'uncovered': [domain], 'comment': Markdown}.
    `chosen` is the author's pick, requested in place of the suggestion; `uncovered` names the
    gated domains it doesn't cover as a P1 or P2, and `with_suggested` requests their picks too.
    ValueError when chosen names the PR's author, or the verdict isn't for the PR's head."""
    raise NotImplementedError


def send(number: int, plan: dict, github=github) -> dict:
    """The plan's comment when it posts, then its request: {'comment': url | None, 'requested': [login]}."""
    raise NotImplementedError


def read(body: str) -> dict | None:
    """A comment's last handoff block, or None without one or for a version it doesn't know."""
    raise NotImplementedError


def _facts(number: int) -> dict:
    """Every read a plan needs: {'viewer', 'author', 'body', 'base', 'head', 'rules': list | None,
    'changed': [path], 'load': {login: open requests}, 'engaged': [login], 'handoffs': [block]},
    where engaged is each person requested or with a submitted review, and handoffs are the
    viewer's own, oldest first."""
    raise NotImplementedError

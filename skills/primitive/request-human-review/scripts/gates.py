#!/usr/bin/env python3
"""request-human-review's gate verdict: which of a PR's decisions need a human, and what an
unattended reviewer does with the PR. The rule lives here once; post-review.py acts on it.

GATES.json, written by the agent from the whole PR (base...head), never a re-review's delta:

    {"pr": 412, "base": "<sha>", "head": "<sha>",
     "decisions": [{"id": "D2" | null, "decision": "one line", "code": "path:line",
                    "gate": "one-way-door" | "pattern" | "interface" | "product" | null,
                    "why": "what makes it a gate, or the precedent it follows as path:line"}],
     "sensitive": [{"area": "money-movement" | "auth" | "tenancy" | "concurrency" | "dependencies",
                    "code": "path:line"}]}

Every row of the PR's Decisions table has an entry under its `D<n>` id; a decision found in
the diff that the table lacks has `"id": null`. A decision whose gate is null follows an
established pattern, so it needs no human. A sensitive area gets a deeper review, never a gate.

    gates.py check N GATES.json   exit 1 naming each problem, read against the PR's body and head
    gates.py decide GATES.json    what an unattended reviewer would do with no held finding
    gates.py own-diff BASE HEAD   the PR's own-diff fingerprint, run in the repository's checkout
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

GATES = {'one-way-door': 'one-way door', 'pattern': 'new or changed pattern',
         'interface': 'architectural or interface decision', 'product': 'important product decision'}
AREAS = ('money-movement', 'auth', 'tenancy', 'concurrency', 'dependencies')
# What an unattended reviewer does, from the most to the least blocking.
ACTIONS = ('request-changes', 'needs-human', 'not-approved', 'wait', 'approve')
REQUIRED = ('passed', 'pending', 'failed')
# Whether the review's read-only pass by the other provider ran: not-needed is review-code's
# skip for a diff that changes no behavior; missing is any other reason it didn't run.
SECOND_OPINION = ('ran', 'not-needed', 'missing')
SHA = re.compile(r'[0-9a-f]{40}')
TABLE_ROW = re.compile(r'^\s*\|\s*(D\d+)\s*\|', re.M)


def load(path) -> dict:
    """GATES.json, refused with every shape problem named."""
    verdict = json.loads(Path(path).read_text())
    problems = []
    if type(verdict.get('pr')) is not int:
        problems.append('pr is not a PR number')
    for field in ('base', 'head'):
        if not SHA.fullmatch(str(verdict.get(field))):
            problems.append(f'{field} is not a full commit SHA')
    for index, decision in enumerate(verdict.get('decisions', [])):
        name = decision.get('id') or f'decision {index + 1}'
        if decision.get('gate') not in (*GATES, None):
            problems.append(f'{name}: gate {decision.get("gate")!r} is not one of {", ".join(GATES)}, or null')
        for field in ('decision', 'code', 'why'):
            if not str(decision.get(field) or '').strip():
                problems.append(f'{name}: {field} is empty')
    for entry in verdict.get('sensitive', []):
        if entry.get('area') not in AREAS or not str(entry.get('code') or '').strip():
            problems.append(f'sensitive entry {entry} needs an area from {", ".join(AREAS)} and its code')
    if problems:
        raise ValueError('GATES.json: ' + '; '.join(problems))
    return verdict


def check(verdict: dict, pr_body: str, head: str) -> list:
    """Problems with a loaded verdict against the PR now: a moved head, or a Decisions-table
    row with no entry of its own."""
    problems = [] if verdict['head'] == head else [f'the verdict judged {verdict["head"]}, but the head is {head}']
    covered = {decision['id'] for decision in verdict['decisions']}
    problems += [f'{row} from the Decisions table has no entry' for row in dict.fromkeys(TABLE_ROW.findall(pr_body))
                 if row not in covered]
    return problems


def own_diff(base: str, head: str, cwd: str = '.') -> str:
    """A fingerprint of the PR's own diff, from the merge base of base and head to head: equal
    fingerprints mean byte-identical diffs, file modes and binary files included. It hashes git's
    raw tree diff, where each changed path carries both modes and both blob ids, and a blob id is
    the hash of the file's bytes, so no file needs reading."""
    def git(*arguments):
        # Bytes: text mode would turn a path's carriage return into a newline before hashing.
        return subprocess.run(['git', '-C', cwd, *arguments], capture_output=True, check=True, timeout=120).stdout
    fork = git('merge-base', base, head).decode().strip()
    raw = git('diff-tree', '-r', '--no-renames', '--no-abbrev', '--full-index', '-z', fork, head)
    return hashlib.sha256(raw).hexdigest()


def gated(verdict: dict) -> list:
    """The decisions that need a human."""
    return [decision for decision in verdict['decisions'] if decision['gate']]


def decide(verdict: dict, holds: bool, required: str, second_opinion: str) -> str:
    """The unattended reviewer's action. A finding that holds the approval requests changes; a
    gate, or a review whose second opinion didn't run, needs a human; otherwise the PR's
    required checks on its head decide."""
    if required not in REQUIRED:
        raise ValueError(f'required is one of {", ".join(REQUIRED)}')
    if second_opinion not in SECOND_OPINION:
        raise ValueError(f'second_opinion is one of {", ".join(SECOND_OPINION)}')
    if holds:
        return 'request-changes'
    if gated(verdict) or second_opinion == 'missing':
        return 'needs-human'
    return {'passed': 'approve', 'pending': 'wait', 'failed': 'not-approved'}[required]


def section(verdict: dict, no_second_opinion: str | None = None) -> str:
    """The review's "Needs a human" Markdown, naming each gated decision, and, given why, that
    the review's second opinion didn't run."""
    lines = ['**Needs a human.** ' + ("These decisions need a person's approval; the rest of the PR follows "
                                     'established patterns:' if gated(verdict) else 'A person approves this PR:'), '']
    for decision in gated(verdict):
        label = decision['id'] or 'Not in the Decisions table'
        lines.append(f'- **{label}** · {GATES[decision["gate"]]}: {decision["decision"]} · `{decision["code"]}` · '
                     f'{decision["why"]}')
    if no_second_opinion is not None:
        lines.append(f"- **Second opinion** · the other provider's review didn't run ({no_second_opinion}), "
                     'so a person reviews in its place')
    return '\n'.join(lines) + '\n'


def main(arguments):
    if len(arguments) == 3 and arguments[0] == 'check':
        verdict = load(arguments[2])
        pr = json.loads(subprocess.run(['gh', 'pr', 'view', arguments[1], '--json', 'body,headRefOid'],
                                       capture_output=True, text=True, check=True, timeout=60).stdout)
        problems = check(verdict, pr['body'], pr['headRefOid'])
        print('\n'.join(problems) or f'{arguments[2]} covers the PR at {verdict["head"]}')
        return 1 if problems else 0
    if len(arguments) == 3 and arguments[0] == 'own-diff':
        print(own_diff(arguments[1], arguments[2]))
        return 0
    if len(arguments) == 2 and arguments[0] == 'decide':
        verdict = load(arguments[1])
        action = decide(verdict, holds=False, required='passed', second_opinion='ran')
        print('needs a human: ' + ', '.join(decision['id'] or decision['decision'] for decision in gated(verdict))
              if action == 'needs-human' else 'no gate: an unattended reviewer approves once nothing holds it, '
              'its second opinion ran or the PR changes no behavior, and the required checks pass on this head')
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))

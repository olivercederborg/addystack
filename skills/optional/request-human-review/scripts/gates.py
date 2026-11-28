#!/usr/bin/env python3
"""request-human-review's gate verdict: which of a PR's decisions need a human, and what an
unattended reviewer does with the PR. The rule lives here once; post-review.py acts on it.

GATES.json, written by the agent from the whole PR (base...head), never a re-review's delta:

    {"pr": 412, "base": "<sha>", "head": "<sha>",
     "decisions": [{"id": "D2" | null, "decision": "one line", "code": "path:line",
                    "gate": "one-way-door" | "pattern" | "interface" | "product" | null,
                    "why": "what makes it a gate, or the precedent it follows as path:line",
                    "ask": "the question the human answers; a gated decision only"}],
     "sensitive": [{"area": "money-movement" | "auth" | "tenancy" | "concurrency" | "dependencies",
                    "code": "path:line"}]}

Every row of the PR's Decisions table has an entry under its `D<n>` id; a decision found in
the diff that the table lacks has `"id": null`. A decision whose gate is null follows an
established pattern, so it needs no human, unless the repository's own one-way doors name its
kind. A sensitive area gets a deeper review, and a gate only when those one-way doors name it.

    gates.py check N GATES.json   exit 1 naming each problem, read against the PR's body and head,
                                  and the one-way doors its PR template lists at the base
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
# A repository's own list of one-way doors, in a PR template where GitHub looks for one.
# The list ends with its sentence, a blank line, a heading, or the comment it sits in.
DOORS = re.compile(r'one-way\s+doors\s+include:?\s+(.+?)(?=\.(?:\s|\Z)|-->|\n\s*\n|\n\s*#|\Z)', re.I | re.S)
ITEM = re.compile(r'[,;]|\s(?:and|or)\s')
# Markdown emphasis and code marks, and an aside in parentheses, are not part of an item's name.
PLAIN = re.compile(r'[*`]|\([^)]*\)')
TEMPLATE = re.compile(r'(\.github/|docs/)?pull_request_template\.md', re.I)
TEMPLATE_FOLDERS = ('.github/', '', 'docs/')


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
        for field in ('decision', 'code', 'why') + (('ask',) if decision.get('gate') else ()):
            if not str(decision.get(field) or '').strip():
                problems.append(f'{name}: {field} is empty')
    for entry in verdict.get('sensitive', []):
        if entry.get('area') not in AREAS or not str(entry.get('code') or '').strip():
            problems.append(f'sensitive entry {entry} needs an area from {", ".join(AREAS)} and its code')
    if problems:
        raise ValueError('GATES.json: ' + '; '.join(problems))
    return verdict


def check(verdict: dict, pr_body: str, head: str, number: int | None = None) -> list:
    """Problems with a loaded verdict against the PR now: another PR's verdict, a moved head, or a
    Decisions-table row with no entry of its own."""
    problems = [] if number is None or verdict['pr'] == number else [f'the verdict is for #{verdict["pr"]}, not #{number}']
    problems += [] if verdict['head'] == head else [f'the verdict judged {verdict["head"]}, but the head is {head}']
    covered = {decision['id'] for decision in verdict['decisions']}
    problems += [f'{row} from the Decisions table has no entry' for row in dict.fromkeys(TABLE_ROW.findall(pr_body))
                 if row not in covered]
    return problems


def one_way_doors(base: str, cwd: str = '.') -> tuple | None:
    """The repository's own one-way doors at base, as ("path:line", "the list"): the "One-way doors
    include …" sentence of the PR template GitHub uses, the first in .github/, the root, then
    docs/. None when that template lists none, or there is none."""
    def git(*arguments):
        return subprocess.run(['git', '-C', cwd, *arguments], capture_output=True, text=True, check=True,
                              timeout=60).stdout
    # --full-tree: the paths are the repository's, whatever folder the review runs in.
    templates = [path for path in git('ls-tree', '--full-tree', '--name-only', base, '--', './', '.github/', 'docs/')
                 .splitlines() if TEMPLATE.fullmatch(path)]
    if not templates:
        return None
    path = min(templates, key=lambda path: TEMPLATE_FOLDERS.index(path[:path.rfind('/') + 1]))
    # The whole file: a Markdown sentence can wrap across lines.
    text = git('show', f'{base}:{path}')
    if not (match := DOORS.search(text)):
        return None
    return f'{path}:{text.count(chr(10), 0, match.start()) + 1}', ' '.join(match.group(1).split())


def doors(verdict: dict, base: str, cwd: str = '.') -> list:
    """Problems with a verdict against the repository's own one-way doors at base, the PR's base
    now: a sensitive area that is an item of their list by its own name is a one-way door even
    when it follows a pattern, so it needs a one-way-door decision at its code. A narrower item,
    such as authorization changes, is the agent's to gate."""
    definition = one_way_doors(base, cwd)
    if definition is None:
        return []
    source, listed = definition
    items = {item.strip().lower() for item in ITEM.split(PLAIN.sub('', listed))}
    covered = {decision['code'] for decision in verdict['decisions'] if decision['gate'] == 'one-way-door'}
    return [f'{entry["area"]} at {entry["code"]} is a one-way door by {source}: it needs a one-way-door '
            'decision at that code' for entry in verdict['sensitive']
            if items & {entry['area'], entry['area'].replace('-', ' ')} and entry['code'] not in covered]
def current(verdict: dict, pr_body: str, base: str, head: str, number: int | None = None) -> list:
    """Every problem with acting on a loaded verdict now: check's, then, once those pass, a PR
    whose diff against its current base isn't the one judged from the verdict's base, as after
    a move to another base, then the repository's one-way doors at that base. Each caller that
    acts on a verdict asks this, so they stay in step."""
    problems = check(verdict, pr_body, head, number)
    if not problems and not same_diff(verdict['base'], base, head):
        problems.append(f"the PR's diff against its base is not the one the gates judged from {verdict['base']}; "
                        'review it again')
    return problems or doors(verdict, base)


def same_diff(judged_base: str, base: str, head: str, cwd: str = '.') -> bool:
    """Whether head's own diff against base is the one judged against judged_base: a PR moved to
    another base can change its diff with the same head, while a base that only moved on leaves
    it. Fetches the commits it compares when it can; one still missing fails in the diff."""
    subprocess.run(['git', '-C', cwd, 'fetch', '--quiet', 'origin', judged_base, base, head],
                   capture_output=True, timeout=600)
    return own_diff(judged_base, head, cwd) == own_diff(base, head, cwd)


def own_diff(base: str, head: str, cwd: str = '.') -> str:
    """A fingerprint of the PR's own diff, from the merge base of base and head to head: equal
    fingerprints mean byte-identical diffs, file modes and binary files included. It hashes git's
    raw tree diff, where each changed path carries both modes and both blob ids, and a blob id is
    the hash of the file's bytes, so no file needs reading."""
    def git(*arguments):
        # Bytes: text mode would turn a path's carriage return into a newline before hashing.
        return subprocess.run(['git', '-C', cwd, *arguments], capture_output=True, check=True, timeout=120).stdout
    fork = git('merge-base', base, head).decode().strip()
    # A submodule set to ignore changes would otherwise drop out of the diff.
    raw = git('diff-tree', '-r', '--no-renames', '--no-abbrev', '--full-index', '--ignore-submodules=none', '-z', fork, head)
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


def line(decision: dict) -> str:
    """A gated decision as one Markdown list item, the same in a review and a handoff."""
    label = decision['id'] or 'Not in the Decisions table'
    return f'- **{label}** · {GATES[decision["gate"]]}: {decision["decision"]} · `{decision["code"]}` · {decision["why"]}'


def section(verdict: dict, no_second_opinion: str | None = None) -> str:
    """The review's "Needs a human" Markdown, naming each gated decision, and, given why, that
    the review's second opinion didn't run."""
    lines = ['**Needs a human.** ' + ("These decisions need a person's approval; the rest of the PR follows "
                                     'established patterns:' if gated(verdict) else 'A person approves this PR:'), '']
    lines += [line(decision) for decision in gated(verdict)]
    if no_second_opinion is not None:
        lines.append(f"- **Second opinion** · the other provider's review didn't run ({no_second_opinion}), "
                     'so a person reviews in its place')
    return '\n'.join(lines) + '\n'


def main(arguments):
    if len(arguments) == 3 and arguments[0] == 'check':
        verdict = load(arguments[2])
        pr = json.loads(subprocess.run(['gh', 'pr', 'view', arguments[1], '--json', 'body,headRefOid,baseRefOid'],
                                       capture_output=True, text=True, check=True, timeout=60).stdout)
        problems = current(verdict, pr['body'], pr['baseRefOid'], pr['headRefOid'], int(arguments[1]))
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

#!/usr/bin/env python3
"""request-human-review's one GitHub writer for an unattended review. It re-reads the PR's
head and required checks, applies gates.decide, and posts exactly one outcome as the App
that gh is signed in as: an approval, a request for changes, or the decisions that need a
human. It refuses to post as a person, whose review goes through review-code with their go.

REVIEW.json, written by the reviewing agent, with paths relative to its own folder:

    {"pr": 412, "head": "<the sha every finding was verified at>", "gates": "GATES.json",
     "body": "BODY.md",
     "findings": [{"call": "blocking" | "non-blocking" | "question", "holds": true | false,
                   "title": "one line",
                   "draft": {"path", "line", "side"?, "start_line"?, "start_side"?, "body_file"}?}]}

BODY.md is the review's summary and starts with the agent disclosure. `holds` is
review-code's rule for a finding that holds the approval.

    post-review.py N REVIEW.json [--wait SECONDS]

It prints one Outcome line, {"outcome", "head", "review"?, "gated"?, "checks"?}, where
outcome is approved, changes-requested, needs-human, not-approved (required checks failed
or never finished within --wait), or superseded (the head moved; nothing posted, since the
push starts its own review). Exit 0 posted, 3 superseded, 1 refused or failed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates  # noqa: E402

GITHUB = Path(__file__).resolve().parent / 'github.sh'
POLL_SECONDS = 60
PASSED = ('pass', 'skipping')
FAILED = ('fail', 'cancel')


def github(*arguments) -> str:
    result = subprocess.run([str(GITHUB), *map(str, arguments)], capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError(f'github.sh {arguments[0]} failed: {(result.stderr or result.stdout).strip()[-400:]}')
    return result.stdout


def pr(number: int) -> dict:
    result = subprocess.run(['gh', 'pr', 'view', str(number), '--json', 'body,headRefOid'], capture_output=True,
                            text=True, timeout=120)
    if result.returncode:
        raise ValueError(f'gh pr view {number} failed: {result.stderr.strip()[-400:]}')
    return json.loads(result.stdout)


def required(number: int) -> tuple:
    """'passed', 'pending' or 'failed' for the base's required checks on the head, with each
    one that hasn't passed. A draft whose CI skipped is pending: it never approves."""
    lines = github('required', number).splitlines()
    open_checks = [line for line in lines if '\t' in line and line.split('\t', 1)[1] not in PASSED]
    if any(line.split('\t', 1)[1] in FAILED for line in open_checks):
        return 'failed', open_checks
    return ('passed', []) if 'required: all passed' in lines else ('pending', open_checks or lines[-1:])


def _user(login: str) -> str:
    """GraphQL names an App's bot without the [bot] REST and viewer give it."""
    return login.removesuffix('[bot]')


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text)
    return path


def _notes(findings: list, heading: str) -> str:
    if not findings:
        return ''
    lines = [f'**{heading}**', '']
    for finding in findings:
        where = f' · `{finding["draft"]["path"]}:{finding["draft"]["line"]}`' if finding.get('draft') else ''
        lines.append(f'- {finding["call"]}: {finding["title"]}{where}')
    return '\n' + '\n'.join(lines) + '\n'


def post(number: int, review_path: Path, wait_seconds: int, now=time.monotonic, sleep=time.sleep) -> dict:
    review = json.loads(review_path.read_text())
    folder = review_path.resolve().parent
    if review['pr'] != number:
        raise ValueError(f'{review_path} is for #{review["pr"]}, not #{number}')
    viewer = github('viewer').strip()
    if not viewer.endswith('[bot]'):
        raise ValueError(f'gh posts as {viewer}, a person: post-review.py posts only as an App')
    verdict = gates.load(folder / review['gates'])
    current = pr(number)
    head = review['head']
    superseded = {'outcome': 'superseded', 'head': current['headRefOid']}
    if current['headRefOid'] != head:
        return superseded
    problems = gates.check(verdict, current['body'], head)
    if problems:
        raise ValueError('; '.join(problems))
    findings = review['findings']
    holds = any(finding['holds'] for finding in findings)
    # Checks matter only when nothing else decides; a held finding or a gate never approves.
    state, checks = ('passed', []) if holds or gates.gated(verdict) else required(number)
    action = gates.decide(verdict, holds, state)
    deadline = now() + wait_seconds
    while action == 'wait':
        if now() >= deadline:
            action = 'not-approved'
            break
        sleep(POLL_SECONDS)
        moved = github('head', number).strip()
        if moved != head:
            return {**superseded, 'head': moved}
        state, checks = required(number)
        action = gates.decide(verdict, holds, state)
    earlier = github('reviewed', number).strip()
    standing = json.loads(earlier) if earlier else None
    # Right before the write: a push since the checks read starts its own review.
    moved = github('head', number).strip()
    if moved != head:
        return {**superseded, 'head': moved}
    body = (folder / review['body']).read_text()
    outcome = {'head': head}
    with tempfile.TemporaryDirectory(dir=folder) as scratch:
        scratch = Path(scratch)
        if action == 'approve':
            # No inline comments: an open thread would hold the merge until someone resolves it.
            body += _notes(findings, 'Notes that don\'t hold the approval')
            for thread in map(json.loads, filter(None, github('threads', number).splitlines())):
                if not thread['isResolved'] and _user(thread['comments'][0]['author'] or '') == _user(viewer):
                    github('resolve', thread['id'])
            outcome['review'] = github('approve', number, head, '', _write(scratch, 'body.md', body)).strip()
            outcome['outcome'] = 'approved'
        else:
            drafts = [finding['draft'] for finding in findings if finding.get('draft')]
            body += _notes([finding for finding in findings if not finding.get('draft')], 'Findings')
            if gates.gated(verdict):
                body += '\n' + gates.section(verdict)
                outcome['gated'] = [decision['id'] or decision['decision'] for decision in gates.gated(verdict)]
            if action == 'not-approved':
                body += '\n**Not approved:** these required checks did not pass on this head:\n\n' + \
                        '\n'.join(f'- {line}' for line in checks) + '\n'
                outcome['checks'] = checks
            # Drafts name their body files relative to REVIEW.json's folder, so they sit there too.
            drafts_path = _write(folder, f'{scratch.name}-drafts.json', json.dumps(drafts))
            event = 'REQUEST_CHANGES' if action == 'request-changes' else 'COMMENT'
            outcome['review'] = github('review', number, head, drafts_path, event, _write(scratch, 'body.md', body)).strip()
            outcome['outcome'] = {'request-changes': 'changes-requested', 'needs-human': 'needs-human',
                                  'not-approved': 'not-approved'}[action]
            # An earlier request for changes still blocks the merge after its findings are fixed.
            if action != 'request-changes' and standing and standing['state'] == 'CHANGES_REQUESTED':
                github('dismiss', number, standing['id'], _write(
                    scratch, 'dismissal.md', f'Superseded at {head[:7]}: no finding holds the approval now.'))
        for leftover in folder.glob(f'{scratch.name}-*.json'):
            leftover.unlink()
    return outcome


def main(arguments) -> int:
    parser = argparse.ArgumentParser(description='Post an unattended review outcome as the App.')
    parser.add_argument('number', type=int)
    parser.add_argument('review', type=Path)
    parser.add_argument('--wait', type=int, default=0, help='seconds to wait for pending required checks')
    args = parser.parse_args(arguments)
    outcome = post(args.number, args.review, args.wait)
    print(json.dumps(outcome))
    return 3 if outcome['outcome'] == 'superseded' else 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f'post-review.py: {error}', file=sys.stderr)
        sys.exit(1)

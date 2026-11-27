#!/usr/bin/env python3
"""review-decisions' drafts block: the review a reviewer agreed to in a --slack thread, as the
last line of the reply, for a poster that posts it as that reviewer. It names nobody, so
whoever posts it decides whose review it becomes.

    <!-- review-decisions:drafts v1 {json} -->

    {"pr": 12, "head": "<the 40-hex commit the drafts were written at>", "summary": "the review's body",
     "comments": [{"path", "line": > 0, "side": "RIGHT" | "LEFT", "start_line"?: <= line, "body"}],
     "replies": [{"in_reply_to": <the thread's review comment id>, "body"}]}

No comments and no replies is an approval, with the summary as its body, which may be empty.
`<` and `>` in the JSON are escaped as \\u003c and \\u003e, so no body can close the comment.
A field added later keeps v1; a renamed or removed one is v2. A reader takes the last block in
a message, and nothing when that block is another version or malformed.

    drafts.py check FILE   print FILE's drafts as their block; exit 1 naming each problem
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

MARK, VERSION = 'review-decisions:drafts', 1
BLOCK = re.compile(rf'<!-- {MARK} v(\d+)\s(.*?)\s*-->', re.S)
SHA = re.compile(r'[0-9a-f]{40}')
SIDES = ('RIGHT', 'LEFT')


def problems(drafts) -> list[str]:
    """Each way the drafts break the v1 shape; none when a poster can post them."""
    if not isinstance(drafts, dict):
        return ['the drafts are not a JSON object']
    found = []
    if not _positive(drafts.get('pr')):
        found.append('pr is not a PR number')
    if not isinstance(drafts.get('head'), str) or not SHA.fullmatch(drafts['head']):
        found.append('head is not a full commit SHA')
    if not isinstance(drafts.get('summary'), str):
        found.append('summary is not a string')
    for field, label, check in (('comments', 'comment', _comment), ('replies', 'reply', _reply)):
        entries = drafts.get(field)
        if not isinstance(entries, list):
            found.append(f'{field} is not a list')
            continue
        for index, entry in enumerate(entries, 1):
            found += [f'{label} {index}: {problem}' for problem in
                      (check(entry) if isinstance(entry, dict) else ['is not an object'])]
    return found


def render(drafts: dict) -> str:
    """The drafts' block, or ValueError naming each problem."""
    found = problems(drafts)
    if found:
        raise ValueError('; '.join(found))
    payload = json.dumps(drafts, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
    return f'<!-- {MARK} v{VERSION} {payload} -->'


def read(text: str) -> dict | None:
    """The last block's drafts, or None without one, or when it is another version or malformed."""
    blocks = BLOCK.findall(text or '')
    if not blocks or int(blocks[-1][0]) != VERSION:
        return None
    try:
        drafts = json.loads(blocks[-1][1])
    except ValueError:
        return None
    return None if problems(drafts) else drafts


def _positive(value) -> bool:
    """A whole number above zero; JSON's true and false aren't numbers here."""
    return type(value) is int and value > 0


def _body(entry: dict) -> list[str]:
    body = entry.get('body')
    if not isinstance(body, str):
        return ['body is not a string']
    return [] if body.strip() else ['body is empty']


def _comment(comment: dict) -> list[str]:
    found = []
    if not isinstance(comment.get('path'), str) or not comment['path']:
        found.append('path is empty')
    if not _positive(comment.get('line')):
        found.append('line is not a positive number')
    if comment.get('side') not in SIDES:
        found.append("side is not 'RIGHT' or 'LEFT'")
    if 'start_line' in comment:
        start = comment['start_line']
        if not _positive(start) or (_positive(comment.get('line')) and start > comment['line']):
            found.append('start_line is not a positive number at or before line')
    if 'start_side' in comment and comment['start_side'] != comment.get('side'):
        found.append('start_line is on another side than line')
    return found + _body(comment)


def _reply(reply: dict) -> list[str]:
    return ([] if _positive(reply.get('in_reply_to')) else ['in_reply_to is not a review comment id']) + _body(reply)


def main(arguments: list[str]) -> int:
    if len(arguments) != 2 or arguments[0] != 'check':
        print('usage: drafts.py check FILE', file=sys.stderr)
        return 2
    try:
        drafts = json.loads(Path(arguments[1]).read_text())
    except ValueError as error:
        print(f'{arguments[1]} is not JSON: {error}', file=sys.stderr)
        return 1
    found = problems(drafts)
    if found:
        print(*found, sep='\n', file=sys.stderr)
        return 1
    print(render(drafts))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

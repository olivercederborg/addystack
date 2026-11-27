#!/usr/bin/env python3
"""request-human-review's handoff: when a PR needs a human, one PR comment that hands the
gated decisions to whoever reviews them, then a review request to the people REVIEWERS
names. The comment is written for the agent that runs the human's review: a one-line header
for people glancing at the PR, every decision in full, and a versioned block that `read`
parses. It names whom it asks without an @mention, since the request notifies them, and says
asking, not requested, since it posts before the request, which GitHub may refuse.

An unattended review hands off through post-review.py once its needs-human review posted. A
PR's author runs it with their go, and may name the reviewer:

    handoff.py N GATES.json [--reviewer LOGIN]... [--with-suggested]   print the draft
    handoff.py N GATES.json [--reviewer LOGIN]... [--with-suggested] --disclosure LINE --send

`--send` posts the comment, then requests. It never requests the PR's author. A handoff of
the same decisions as the signed-in login's own last one posts no comment, and still requests
whoever the pick needs, so a run that commented and then failed to request finishes on a
retry. Someone else's handoff, such
as the author's, never stands in for this login's own. A base without `.github/REVIEWERS`
hands off nothing.

The block, the comment's last lines; a field added later keeps v1, a renamed or removed one
is v2, and a reader takes the last block it trusts:

    <!-- addystack-handoff:v1
    {"pr", "base", "head", "by", "chosen_by": "rule" | "author", "second_opinion": why | null,
     "decisions": [{"key", "id", "gate", "decision", "ask", "why", "code", "domain"}],
     "reviewers": [{"login", "role", "domains"}], "engaged": [login]}
    -->
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates  # noqa: E402
import reviewers  # noqa: E402
import standing  # noqa: E402

GITHUB = Path(__file__).resolve().parent / 'github.sh'
MARK, VERSION = 'addystack-handoff', 1
SECOND_OPINION = 'second-opinion'
BLOCK = re.compile(rf'<!-- {MARK}:v(\d+)\n(.*?)\n-->', re.S)
ROLES = {'P1': 'P1', 'P2': 'P2', 'P3': 'P3', 'fallback': 'not listed here, least loaded',
         'chosen': 'chosen by the author'}


def _error(output: str) -> str:
    """A failed command's error for a review's body: without the hint block gh prints after
    some commands, such as `gh pr view`'s about `gh event listen`, whose indented lines follow it."""
    lines, hint = [], False
    for line in output.splitlines():
        hint = line.startswith('hint:') or (hint and line.startswith(' '))
        if not hint and line.strip():
            lines.append(line)
    return '\n'.join(lines)[-400:]


def github(*arguments) -> str:
    """github.sh with these arguments, its stdout, or ValueError with its error."""
    result = subprocess.run([str(GITHUB), *map(str, arguments)], capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError(f'github.sh {arguments[0]} failed: {_error(result.stderr or result.stdout)}')
    return result.stdout


def key(decision: dict) -> str:
    """A decision's identity across reviews: its Decisions-table id, or the path in its `code`
    when it has none, with its gate. Wording and line numbers change between reviews."""
    return f'{decision.get("id") or reviewers.file_of(decision["code"])}:{decision["gate"]}'


def plan(number: int, verdict: dict, disclosure: str, no_second_opinion: str | None = None,
         chosen: tuple = (), with_suggested: bool = False) -> dict:
    """What a handoff would post, from reads only:
    {'post': bool, 'why', 'head', 'decisions': [placed], 'request': [reviewer],
     'suggested': [reviewer], 'uncovered': [domain], 'comment': Markdown}.
    `chosen` is the author's pick, requested in place of the suggestion; `uncovered` names the
    gated domains it doesn't cover as a P1 or P2, and `with_suggested` requests their picks too.
    ValueError when chosen names the PR's author, or the verdict isn't for the PR's head and its
    diff against the current base."""
    facts = _facts(number)
    if reviewers.has(chosen, facts['author']):
        raise ValueError(f"{facts['author']} wrote the PR, so can't review it")
    problems = gates.current(verdict, facts['body'], facts['base'], facts['head'], number)
    if problems:
        raise ValueError('; '.join(problems))
    if facts['rules'] is None:
        return {'post': False, 'why': f'no {reviewers.PATH} at the base', 'head': facts['head'], 'decisions': [],
                'request': [], 'suggested': [], 'uncovered': [], 'comment': ''}
    decisions = [{**decision, 'key': key(decision)} for decision in gates.gated(verdict)]
    if no_second_opinion is not None:
        decisions.append({'key': SECOND_OPINION, 'id': None, 'gate': None, 'code': '', 'why': no_second_opinion,
                          'decision': "The other provider's review of the whole PR didn't run",
                          'ask': 'Review the whole PR in its place: is anything here wrong or risky?'})
    placed = reviewers.place(facts['rules'], decisions, facts['changed'])
    author, engaged = facts['author'], facts['engaged']
    weights, held = facts['settings']['weights'], _held(facts['handoffs'], engaged)
    suggested = reviewers.pick(facts['rules'], placed, author, engaged, facts['standing'], weights, held)
    uncovered = []
    if chosen:
        # The pick's own coverage: the listed domains where it is a P1 or P2.
        listed = sorted({decision['domain'] for decision in placed
                         if decision['domain'] and reviewers.names(facts['rules'], decision['domain'])})
        def covers(login):
            return [name for name in listed if reviewers.has(reviewers.names(facts['rules'], name)[:2], login)]
        uncovered = [name for name in listed if not any(name in covers(login) for login in chosen)]
        # Someone already requested, or whose review of this head stands, isn't asked again.
        request = [{'login': login, 'role': 'chosen', 'domains': covers(login)} for login in reviewers.unique(chosen)
                   if not reviewers.has(engaged, login)]
        if with_suggested:
            request += reviewers.pick(facts['rules'], placed, author, [*engaged, *chosen], facts['standing'], weights,
                                      held)
    else:
        request = list(suggested)
    last = facts['handoffs'][-1] if facts['handoffs'] else None
    same = last is not None and sorted(decision['key'] for decision in placed) == \
        sorted(decision['key'] for decision in last['decisions'])
    named = [reviewer['login'] for reviewer in last['reviewers']] if same else []
    new = [reviewer for reviewer in request if not reviewers.has(named, reviewer['login'])]
    if not request and not engaged:
        why = 'nobody to ask'
    elif not same:
        why = 'decisions changed' if last else 'first handoff'
    else:
        why = 'new reviewer' if new else 'nothing new'
    result = {'post': not same or bool(new), 'why': why, 'head': facts['head'], 'decisions': placed,
              'request': request, 'suggested': suggested, 'uncovered': uncovered}
    block = {'pr': number, 'base': facts['base'], 'head': facts['head'], 'by': facts['viewer'],
             'chosen_by': 'author' if chosen else 'rule', 'second_opinion': no_second_opinion,
             'decisions': [{field: decision.get(field) for field in
                            ('key', 'id', 'gate', 'decision', 'ask', 'why', 'code', 'domain')} for decision in placed],
             'reviewers': request, 'engaged': engaged}
    return {**result, 'comment': _render(disclosure, block, facts['rules'])}


def _held(handoffs: list, engaged: list) -> dict:
    """{domain: login}: whom its own earlier handoffs picked for each domain, the latest winning,
    while that person is still requested or has reviewed. So a re-review leaves a domain with
    the person picked for it, even one REVIEWERS doesn't list there, instead of asking another."""
    held = {}
    for block in handoffs:
        for reviewer in block.get('reviewers', []):
            if reviewers.has(engaged, reviewer['login']):
                held.update({name: reviewer['login'] for name in reviewer.get('domains', []) if name})
    return held


def send(number: int, plan: dict, github=github) -> dict:
    """The plan's comment when it posts, then its request: {'comment': url | None, 'requested': [login]}."""
    url = None
    with tempfile.TemporaryDirectory() as folder:
        if plan['post']:
            path = Path(folder) / 'handoff.md'
            path.write_text(plan['comment'])
            url = github('comment', number, path).strip().splitlines()[-1]
    logins = reviewers.unique(reviewer['login'] for reviewer in plan['request'])
    if logins:
        github('request', number, *logins)
    return {'comment': url, 'requested': logins}


def read(body: str) -> dict | None:
    """A comment's last handoff block, or None without one or for a version it doesn't know."""
    blocks = BLOCK.findall(body or '')
    if not blocks or int(blocks[-1][0]) != VERSION:
        return None
    try:
        return json.loads(blocks[-1][1])
    except json.JSONDecodeError:
        return None


def _render(disclosure: str, block: dict, rules: list) -> str:
    """The comment: a header line for people, each decision in full for the reviewing agent, the block."""
    asked = ', '.join(f'`{reviewer["login"]}`' for reviewer in block['reviewers']) or \
        ('nobody new' if block['engaged'] else 'nobody')
    count = len(block['decisions'])
    lines = [disclosure,
             f'**Needs a human** · {count} decision{"s" * (count != 1)} at `{block["head"][:7]}` · asking: {asked}'
             + (' · reviewer chosen by the author' if block['chosen_by'] == 'author' else ''), '',
             '<details><summary>Handoff for the reviewing agent</summary>', '',
             f'This hands PR #{block["pr"]} to a human at head `{block["head"]}` (base `{block["base"]}`). '
             'The rest of the PR follows established patterns; these decisions need a person. '
             "Check the PR's head before acting: a newer push may change them.", '']
    for decision in block['decisions']:
        label = decision['id'] or ('Second opinion' if decision['key'] == SECOND_OPINION else 'Not in the Decisions table')
        gate = gates.GATES.get(decision['gate'], 'no second opinion')
        owners = ', '.join(f'{name} (P{index})' for index, name in
                           enumerate(reviewers.names(rules, decision['domain'])[:2], 1)) if decision['domain'] else ''
        lines += [f'### {label} · {gate}', '',
                  f'- **Decide:** {decision["ask"]}',
                  f'- **Decision:** {decision["decision"]}',
                  f'- **Why a human:** {decision["why"]}',
                  *([f'- **Code:** `{decision["code"]}`'] if decision['code'] else []),
                  f'- **Domain:** ' + (f'`{decision["domain"]}`' + (f' · {owners}' if owners else ' · nobody listed')
                                       if decision['domain'] else 'none in REVIEWERS'), '']
    lines += ['### Reviewers', '']
    lines += [f'- `{reviewer["login"]}` · {ROLES[reviewer["role"]]}'
              + (f' · {", ".join(name for name in reviewer["domains"] if name)}' if any(reviewer['domains']) else '')
              for reviewer in block['reviewers']]
    lines += [f'- Already asked: {", ".join(f"`{login}`" for login in block["engaged"])}'] if block['engaged'] else []
    if not block['reviewers']:
        lines.append('- Nobody new: the people already asked cover these decisions' if block['engaged'] else
                     "- Nobody to ask: REVIEWERS names no one here but the PR's author. Ask someone by hand.")
    # Escaped, so no text in the JSON can close the HTML comment.
    payload = json.dumps(block, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
    return '\n'.join(lines + ['', '</details>', '', f'<!-- {MARK}:v{VERSION}', payload, '-->']) + '\n'


def _gh(*arguments, missing_ok: bool = False) -> str | None:
    """gh's stdout; None for a 404 when missing_ok; ValueError for any other failure."""
    result = subprocess.run(['gh', *arguments], capture_output=True, text=True, timeout=300)
    if result.returncode:
        if missing_ok and 'HTTP 404' in result.stderr:
            return None
        raise ValueError(f'gh {arguments[0]} {arguments[1] if len(arguments) > 1 else ""} failed: {_error(result.stderr)}')
    return result.stdout


def _lines(output: str) -> list:
    return [line for line in output.splitlines() if line.strip()]


def _facts(number: int) -> dict:
    """Every read a plan needs: {'viewer', 'author', 'body', 'base', 'head', 'rules': list | None,
    'settings', 'standing': {login: standing}, 'changed': [path], 'engaged': [login],
    'handoffs': [block]}, where engaged is each person requested or with a standing review of the head,
    standing covers everyone REVIEWERS names, and handoffs are the viewer's own, oldest first."""
    repo = 'repos/{owner}/{repo}'
    viewer = github('viewer').strip()
    pr = json.loads(_gh('api', f'{repo}/pulls/{number}'))
    author = pr['user']['login']
    text = _gh('api', f'{repo}/contents/{reviewers.PATH}?ref={pr["base"]["sha"]}',
               '-H', 'Accept: application/vnd.github.raw', missing_ok=True)
    requested = _lines(_gh('api', f'{repo}/pulls/{number}/requested_reviewers', '--jq', '.users[].login'))
    # Only a person's review of this head counts: a push can dismiss an earlier one, and a decision
    # pushed since needs their eyes again.
    reviews = map(json.loads, _lines(_gh('api', '--paginate', f'{repo}/pulls/{number}/reviews?per_page=100', '--jq',
                                         '.[] | {type: .user.type, login: .user.login, state, commit_id} | tojson')))
    reviewed = [review['login'] for review in reviews if review['type'] == 'User' and review['commit_id'] == pr['head']['sha']
                and review['state'] not in ('PENDING', 'DISMISSED')]
    rules = settings = people = None
    if text is not None:
        rules, settings = reviewers.parse(text), reviewers.settings(text)
        everyone = reviewers.unique(name for rule in rules for name in rule['names'])
        people = standing.read(everyone, settings['share_since'], dt.datetime.now(dt.timezone.utc), _gh)
    comments = map(json.loads, _lines(_gh('api', '--paginate', f'{repo}/issues/{number}/comments?per_page=100',
                                          '--jq', '.[] | {login: .user.login, body} | tojson')))
    return {'viewer': viewer, 'author': author, 'body': pr['body'] or '', 'base': pr['base']['sha'],
            'head': pr['head']['sha'], 'rules': rules, 'settings': settings, 'standing': people,
            'changed': _lines(_gh('api', '--paginate', f'{repo}/pulls/{number}/files?per_page=100', '--jq', '.[].filename')),
            'engaged': [login for login in dict.fromkeys(requested + reviewed)
                                      if login.lower() != author.lower()],
            'handoffs': [block for block in (read(comment['body']) for comment in comments
                                             if comment['login'] == viewer) if block]}


def main(arguments) -> int:
    parser = argparse.ArgumentParser(description="Hand a PR's gated decisions to a human, then request them.")
    parser.add_argument('number', type=int)
    parser.add_argument('gates', type=Path)
    parser.add_argument('--reviewer', action='append', default=[], help="the author's pick, in place of the suggestion")
    parser.add_argument('--with-suggested', action='store_true', help='also request the picks for uncovered domains')
    parser.add_argument('--disclosure', help="the comment's first line, required with --send")
    parser.add_argument('--send', action='store_true', help='post the comment and request, after the go')
    args = parser.parse_args(arguments)
    if args.send and not args.disclosure:
        parser.error('--send needs --disclosure')
    drafted = plan(args.number, gates.load(args.gates), args.disclosure or '<disclosure>', None,
                   tuple(args.reviewer), args.with_suggested)
    if args.send:
        print(json.dumps({**send(args.number, drafted), 'why': drafted['why']}))
    else:
        print(json.dumps({field: drafted[field] for field in ('post', 'why', 'request', 'suggested', 'uncovered')},
                         indent=1))
        print(drafted['comment'])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f'handoff.py: {error}', file=sys.stderr)
        sys.exit(1)

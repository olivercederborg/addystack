"""request-human-review's view of each person's review load, for reviewers.pick: their open
asks, their share of recent reviews, and whether they're away, read from the repository's
pull requests in one GraphQL walk and their GitHub statuses in one query. It owns the time
windows, so the pick only weighs the numbers.

    standing = {login.lower(): {'asks': int, 'share': float, 'away': reason | None}}

- **An open ask**: a pending review request on an open PR, made in the last 7 days, of
  someone who hasn't reviewed that PR yet. A request to look again after a push isn't one.
- **A share**: the PRs someone reviewed since `share since`, at most 14 days back, out of
  every PR each person reviewed in that time; bots and authors' own PRs don't count. 0 for
  everyone before the first review.
- **Away**: their GitHub status is Busy and public (a GitHub App's token reads a status shown
  only to the organization as none), or they haven't opened, reviewed or commented on a PR, or
  authored a commit on one (by its author date: GitHub doesn't record who pushed), in the
  last 3 working days, Monday to Friday in UTC.
"""
from __future__ import annotations

import datetime as dt
import json

ASK_DAYS, SHARE_DAYS, AWAY_WORKING_DAYS = 7, 14, 3
PAGE = 50
QUERY = '''
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: %d, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state createdAt updatedAt
        author { login }
        comments(last: 100) { nodes { createdAt author { login } } }
        commits(last: 100) { nodes { commit { authoredDate author { user { login } } } } }
        reviews(last: 100) { nodes { submittedAt author { __typename login } } }
        reviewRequests(first: 100) { nodes { requestedReviewer { ... on User { login } } } }
        timelineItems(itemTypes: [REVIEW_REQUESTED_EVENT], last: 100) {
          nodes { ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on User { login } } } }
        }
      }
    }
  }
}''' % PAGE


def read(logins: list, share_since: dt.date, now: dt.datetime, gh) -> dict:
    """Each login's standing, from the PRs updated in the last 14 days and their statuses. gh
    is handoff's `_gh`; a failed read raises, so nobody's load or presence is ever guessed."""
    return tally(_pulls(gh, now - dt.timedelta(days=SHARE_DAYS)), _busy(gh, logins), logins, share_since, now)


def _busy(gh, logins: list) -> set:
    """The logins whose GitHub status says Busy, lower-cased, in one aliased query."""
    if not logins:
        return set()
    fields = ' '.join(f'u{index}: user(login: {json.dumps(login)}) {{ status {{ indicatesLimitedAvailability }} }}'
                      for index, login in enumerate(logins))
    users = json.loads(gh('api', 'graphql', '-f', f'query={{ {fields} }}'))['data']
    return {login.lower() for index, login in enumerate(logins)
            if ((users[f'u{index}'] or {}).get('status') or {}).get('indicatesLimitedAvailability')}


def _pulls(gh, since: dt.datetime) -> list:
    """The PRs updated since `since`, newest first, a page at a time until one is older."""
    pulls, after = [], None
    while True:
        arguments = ['api', 'graphql', '-F', 'owner={owner}', '-F', 'name={repo}', '-f', f'query={QUERY}']
        page = json.loads(gh(*arguments, *(['-f', f'after={after}'] if after else [])))
        found = page['data']['repository']['pullRequests']
        for pull in found['nodes']:
            if _time(pull['updatedAt']) < since:
                return pulls
            pulls.append(pull)
        if not found['pageInfo']['hasNextPage']:
            return pulls
        after = found['pageInfo']['endCursor']


def tally(pulls: list, busy: set, logins: list, share_since: dt.date, now: dt.datetime) -> dict:
    """The standing of each login from these PR nodes and Busy logins: pure, so tests feed it nodes."""
    asked_since = now - dt.timedelta(days=ASK_DAYS)
    shared_since = max(now - dt.timedelta(days=SHARE_DAYS),
                       dt.datetime.combine(share_since, dt.time(), tzinfo=dt.timezone.utc))
    asks, reviewed, seen = {}, set(), {}
    for pull in pulls:
        author = _login(pull.get('author'))
        # Every submitted review, not latestReviews, which leaves out anyone asked to look again.
        reviews = {}
        for review in pull['reviews']['nodes']:
            if review['submittedAt'] and (review['author'] or {}).get('__typename') == 'User':
                login, at = _login(review['author']), _time(review['submittedAt'])
                reviews[login] = max(reviews.get(login, at), at)
        acts = [(author, pull['createdAt']), *reviews.items(),
                *((_login(comment['author']), comment['createdAt']) for comment in pull['comments']['nodes']),
                *((_login((entry['commit']['author'] or {}).get('user')), entry['commit']['authoredDate'])
                  for entry in pull['commits']['nodes'])]
        for login, at in acts:
            if login:
                at = at if isinstance(at, dt.datetime) else _time(at)
                seen[login] = max(seen.get(login, at), at)
        reviewed |= {(login, pull['number']) for login, at in reviews.items() if login != author and at >= shared_since}
        if pull['state'] != 'OPEN':
            continue
        asked = {}
        for event in pull['timelineItems']['nodes']:
            if login := _login(event.get('requestedReviewer')):
                at = _time(event['createdAt'])
                asked[login] = max(asked.get(login, at), at)
        for request in pull['reviewRequests']['nodes']:
            login = _login(request['requestedReviewer'])
            # A request whose event fell off the last 100 counts as new rather than vanishing.
            if login and login not in reviews and asked.get(login, now) >= asked_since:
                asks[login] = asks.get(login, 0) + 1
    total = len(reviewed)
    present_since = _working_days_before(now, AWAY_WORKING_DAYS)
    def away(login):
        if login in busy:
            return 'Busy'
        if seen.get(login, present_since) < present_since:
            return f'no activity since {seen[login]:%-d %b}'
        return None if login in seen else f'no activity in {SHARE_DAYS} days'
    return {login.lower(): {'asks': asks.get(login.lower(), 0),
                            'share': sum(1 for who, _ in reviewed if who == login.lower()) / total if total else 0.0,
                            'away': away(login.lower())}
            for login in logins}


def _working_days_before(now: dt.datetime, days: int) -> dt.datetime:
    """The moment `days` working days before now, counting back Monday to Friday only: on a
    weekend the count starts from Saturday's start, since no working time has passed since."""
    moment = now
    if now.weekday() >= 5:
        moment = (now - dt.timedelta(days=now.weekday() - 5)).replace(hour=0, minute=0, second=0, microsecond=0)
    while days:
        moment -= dt.timedelta(days=1)
        days -= moment.weekday() < 5
    return moment


def _login(actor: dict | None) -> str | None:
    """An actor's login, lower-cased, since GitHub logins ignore case; None for a team or a ghost."""
    return actor['login'].lower() if actor and actor.get('login') else None


def _time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00'))

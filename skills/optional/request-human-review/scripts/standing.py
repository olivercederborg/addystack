"""request-human-review's view of each person's review load, for reviewers.pick: their open
asks and their share of recent reviews, read from the repository's pull requests in one
GraphQL walk. It owns the time windows, so the pick only weighs the numbers.

    standing = {login.lower(): {'asks': int, 'share': float}}

- **An open ask**: a pending review request on an open PR, made in the last 7 days, of
  someone who hasn't reviewed that PR yet. A request to look again after a push isn't one.
- **A share**: the PRs someone reviewed since `share since`, at most 14 days back, out of
  every PR each person reviewed in that time; bots and authors' own PRs don't count. 0 for
  everyone before the first review.
"""
from __future__ import annotations

import datetime as dt
import json

ASK_DAYS, SHARE_DAYS = 7, 14
PAGE = 50
QUERY = '''
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: %d, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state updatedAt
        author { login }
        latestReviews(first: 100) { nodes { submittedAt author { __typename login } } }
        reviewRequests(first: 100) { nodes { requestedReviewer { ... on User { login } } } }
        timelineItems(itemTypes: [REVIEW_REQUESTED_EVENT], last: 100) {
          nodes { ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on User { login } } } }
        }
      }
    }
  }
}''' % PAGE


def read(logins: list, share_since: dt.date, now: dt.datetime, gh) -> dict:
    """Each login's standing, from the PRs updated in the last 14 days. gh is handoff's `_gh`;
    a failed read raises, so nobody's load is ever guessed."""
    return tally(_pulls(gh, now - dt.timedelta(days=SHARE_DAYS)), logins, share_since, now)


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


def tally(pulls: list, logins: list, share_since: dt.date, now: dt.datetime) -> dict:
    """The standing of each login from these PR nodes: pure, so tests feed it nodes."""
    asked_since = now - dt.timedelta(days=ASK_DAYS)
    shared_since = max(now - dt.timedelta(days=SHARE_DAYS),
                       dt.datetime.combine(share_since, dt.time(), tzinfo=dt.timezone.utc))
    asks, reviewed = {}, set()
    for pull in pulls:
        author = _login(pull.get('author'))
        reviews = {_login(review['author']): _time(review['submittedAt']) for review in pull['latestReviews']['nodes']
                   if review['submittedAt'] and (review['author'] or {}).get('__typename') == 'User'}
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
    return {login.lower(): {'asks': asks.get(login.lower(), 0),
                            'share': sum(1 for who, _ in reviewed if who == login.lower()) / total if total else 0.0}
            for login in logins}


def _login(actor: dict | None) -> str | None:
    """An actor's login, lower-cased, since GitHub logins ignore case; None for a team or a ghost."""
    return actor['login'].lower() if actor and actor.get('login') else None


def _time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00'))

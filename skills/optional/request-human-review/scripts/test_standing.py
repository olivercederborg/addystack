"""standing.py on pull request nodes shaped like GitHub's GraphQL answer: which review requests
count as open asks, how shares are counted, and that the walk stops at the window."""
import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import standing  # noqa: E402

NOW = dt.datetime(2026, 12, 8, 12, tzinfo=dt.timezone.utc)
SINCE = dt.date(2026, 12, 1)


def ago(days):
    return (NOW - dt.timedelta(days=days)).isoformat().replace('+00:00', 'Z')


def pull(number, author='carol', state='OPEN', updated=0, reviews=(), pending=(), asked=()):
    """A PR node: reviews are (login, days ago, type), pending the logins still requested, and
    asked the (login, days ago) review-request events."""
    return {'number': number, 'state': state, 'updatedAt': ago(updated), 'author': {'login': author},
            'latestReviews': {'nodes': [{'submittedAt': ago(days), 'author': {'__typename': kind, 'login': login}}
                                        for login, days, kind in reviews]},
            'reviewRequests': {'nodes': [{'requestedReviewer': {'login': login}} for login in pending]},
            'timelineItems': {'nodes': [{'createdAt': ago(days), 'requestedReviewer': {'login': login}}
                                        for login, days in asked]}}


class Tally(unittest.TestCase):
    def tally(self, *pulls, share_since=SINCE):
        return standing.tally(list(pulls), ['Alice', 'bob', 'dave'], share_since, NOW)

    def test_an_open_ask_is_a_recent_request_to_someone_who_has_not_reviewed_the_pr(self):
        known = self.tally(
            pull(1, pending=['alice'], asked=[('alice', 2)]),
            pull(2, pending=['Alice'], asked=[('alice', 9), ('alice', 1)]),   # asked again yesterday
            pull(3, pending=['alice'], asked=[('alice', 8)]),                 # older than 7 days
            pull(4, pending=['bob'], asked=[('bob', 1)], reviews=[('bob', 3, 'User')]),  # look again after a push
            pull(5, state='MERGED', pending=['dave'], asked=[('dave', 1)]),
            pull(6, pending=['dave']))                                         # its event fell off the last 100
        self.assertEqual({login: entry['asks'] for login, entry in known.items()}, {'alice': 2, 'bob': 0, 'dave': 1})

    def test_a_share_counts_each_reviewed_pr_once_since_the_cutoff_without_bots_or_own_prs(self):
        known = self.tally(
            pull(1, reviews=[('alice', 1, 'User'), ('bob', 2, 'User'), ('frankie-reviewer', 1, 'Bot')]),
            pull(2, reviews=[('alice', 3, 'User')]),
            pull(3, author='bob', reviews=[('bob', 1, 'User'), ('erin', 1, 'User')]),  # erin isn't in the pool
            pull(4, reviews=[('dave', 10, 'User')]))                                   # before `share since`
        self.assertEqual({login: entry['share'] for login, entry in known.items()}, {'alice': 0.5, 'bob': 0.25, 'dave': 0.0})

    def test_the_share_window_is_14_days_when_the_cutoff_is_older(self):
        known = self.tally(pull(1, reviews=[('dave', 13, 'User'), ('bob', 15, 'User')]), share_since=dt.date(2026, 1, 1))
        self.assertEqual((known['dave']['share'], known['bob']['share']), (1.0, 0.0))

    def test_before_the_first_review_everyone_has_a_share_of_0(self):
        self.assertEqual(self.tally(), {login: {'asks': 0, 'share': 0.0} for login in ('alice', 'bob', 'dave')})


class Pulls(unittest.TestCase):
    def test_the_walk_pages_until_a_pr_is_older_than_the_window(self):
        pages = [[pull(1, updated=1), pull(2, updated=5)], [pull(3, updated=13), pull(4, updated=15)], [pull(5, updated=20)]]
        calls = []
        def gh(*arguments):
            calls.append(arguments)
            nodes = pages[len(calls) - 1]
            return json.dumps({'data': {'repository': {'pullRequests': {
                'nodes': nodes, 'pageInfo': {'hasNextPage': True, 'endCursor': f'cursor{len(calls)}'}}}}})
        pulls = standing._pulls(gh, NOW - dt.timedelta(days=14))
        self.assertEqual([entry['number'] for entry in pulls], [1, 2, 3])
        self.assertEqual(len(calls), 2)
        self.assertIn('after=cursor1', calls[1])
        self.assertIn('owner={owner}', calls[0])


if __name__ == '__main__':
    unittest.main()

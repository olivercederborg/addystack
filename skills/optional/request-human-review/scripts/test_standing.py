"""standing.py on pull request nodes shaped like GitHub's GraphQL answer: which review requests
count as open asks, how shares are counted, and that the walk stops at the window."""
import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import standing  # noqa: E402

NOW = dt.datetime(2026, 12, 8, 12, tzinfo=dt.timezone.utc)   # a Tuesday
SINCE = dt.date(2026, 12, 1)


def ago(days):
    return (NOW - dt.timedelta(days=days)).isoformat().replace('+00:00', 'Z')


def pull(number, author='carol', state='OPEN', updated=0, opened=20, reviews=(), pending=(), asked=(),
         comments=(), commits=()):
    """A PR node: reviews are (login, days ago, type), pending the logins still requested, asked
    the (login, days ago) review-request events, and comments and commits (login, days ago)."""
    return {'number': number, 'state': state, 'createdAt': ago(opened), 'updatedAt': ago(updated),
            'author': {'login': author},
            'comments': {'nodes': [{'createdAt': ago(days), 'author': {'login': login}} for login, days in comments]},
            'commits': {'nodes': [{'commit': {'authoredDate': ago(days), 'author': {'user': {'login': login}}}}
                                  for login, days in commits]},
            'reviews': {'nodes': [{'submittedAt': ago(days), 'author': {'__typename': kind, 'login': login}}
                                        for login, days, kind in reviews]},
            'reviewRequests': {'nodes': [{'requestedReviewer': {'login': login}} for login in pending]},
            'timelineItems': {'nodes': [{'createdAt': ago(days), 'requestedReviewer': {'login': login}}
                                        for login, days in asked]}}


class Tally(unittest.TestCase):
    def tally(self, *pulls, share_since=SINCE, busy=()):
        return standing.tally(list(pulls), set(busy), ['Alice', 'bob', 'dave'], share_since, NOW)

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
            pull(2, reviews=[('alice', 3, 'User'), ('alice', 2, 'User')]),            # reviewed twice: one PR
            pull(3, author='bob', reviews=[('bob', 1, 'User'), ('erin', 1, 'User')]),  # erin isn't in the pool
            pull(4, reviews=[('dave', 10, 'User')]))                                   # before `share since`
        self.assertEqual({login: entry['share'] for login, entry in known.items()}, {'alice': 0.5, 'bob': 0.25, 'dave': 0.0})

    def test_the_share_window_is_14_days_when_the_cutoff_is_older(self):
        known = self.tally(pull(1, reviews=[('dave', 13, 'User'), ('bob', 15, 'User')]), share_since=dt.date(2026, 1, 1))
        self.assertEqual((known['dave']['share'], known['bob']['share']), (1.0, 0.0))

    def test_before_the_first_review_everyone_has_a_share_of_0(self):
        self.assertEqual({login: entry['share'] for login, entry in self.tally().items()},
                         {'alice': 0.0, 'bob': 0.0, 'dave': 0.0})

    def test_away_is_busy_or_no_activity_in_the_last_3_working_days(self):
        # NOW is Tuesday noon, so 3 working days back is Thursday noon: the weekend doesn't count.
        known = self.tally(
            pull(1, author='alice', opened=4.9),                                # Thursday, after noon
            pull(2, comments=[('bob', 5.1)], commits=[('bob', 6)]),             # Thursday morning
            pull(3, reviews=[('dave', 1, 'User')]), busy={'dave'})
        self.assertEqual({login: entry['away'] for login, entry in known.items()},
                         {'alice': None, 'bob': 'no activity since 3 Dec', 'dave': 'Busy'})

    def test_on_a_weekend_the_working_days_count_back_from_saturdays_start(self):
        saturday_noon = dt.datetime(2026, 12, 12, 12, tzinfo=dt.timezone.utc)
        self.assertEqual(standing._working_days_before(saturday_noon, 3), dt.datetime(2026, 12, 9, tzinfo=dt.timezone.utc))
        self.assertEqual(standing._working_days_before(NOW, 3), NOW - dt.timedelta(days=5))

    def test_a_comment_or_an_authored_commit_counts_as_activity_and_none_at_all_is_away(self):
        known = self.tally(pull(1, comments=[('alice', 1)], commits=[('bob', 2)]))
        self.assertEqual({login: entry['away'] for login, entry in known.items()},
                         {'alice': None, 'bob': None, 'dave': 'no activity in 14 days'})


class Busy(unittest.TestCase):
    def test_one_query_names_each_busy_login(self):
        queries = []
        def gh(*arguments):
            queries.append(arguments[-1])
            return json.dumps({'data': {'u0': {'status': {'indicatesLimitedAvailability': True}},
                                        'u1': {'status': None}, 'u2': {'status': {'indicatesLimitedAvailability': False}}}})
        self.assertEqual(standing._busy(gh, ['Alice', 'bob', 'carol']), {'alice'})
        self.assertEqual(len(queries), 1)
        self.assertIn('u0: user(login: "Alice")', queries[0])


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

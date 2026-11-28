"""reviewers.py on a REVIEWERS file shaped like a real one: which domain a path is in, where a
decision in no domain goes, and whom a handoff asks."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import reviewers  # noqa: E402

FILE = """# Who reviews each part of the repo: P1 first, then an optional P2.
# CODEOWNERS syntax: the last pattern that matches a path wins.

## web
/apps/web/

## billing
/packages/billing/ @alice @bob
/apps/web/src/features/billing/ @alice @bob

## billing-invoices
/apps/web/src/features/billing/(invoices)/ @carol


## auth · pinned
# P2 is drafted each refresh; only the first name is pinned.
/packages/auth/ @dave @Erin

## conventions
/.agents/ @bob
AGENTS.md @bob

## unowned
# An ADR or a CONTEXT.md belongs to the domain of the PR's main change.
CONTEXT.md
**/docs/adr/
"""
RULES = reviewers.parse(FILE)
WEIGHTS = {'P1': 3, 'P2': 2, 'P3': 1, 'open ask': 1, 'share': 10}


def decision(code, id_='D1'):
    return {'id': id_, 'gate': 'interface', 'code': code}


class Parse(unittest.TestCase):
    def test_every_line_it_cannot_read_is_named(self):
        bad = '## unowned\nCONTEXT.md @alice\n## web\n/apps/web/ alice @team/web\n'
        with self.assertRaises(ValueError) as raised:
            reviewers.parse(bad)
        for named in ('line 2: the unowned block names nobody', 'line 4: alice @team/web'):
            self.assertIn(named, str(raised.exception))

    def test_lines_above_the_first_domain_are_not_rules(self):
        rules = reviewers.parse('# settings\npriority: 3 2 1\n/early/ @alice\n\n## web\n/apps/web/ @bob\n')
        self.assertEqual([(rule['pattern'], rule['domain'], rule['names']) for rule in rules],
                         [('/apps/web/', 'web', ['bob'])])

    def test_settings_come_from_the_lines_above_the_first_domain(self):
        text = '# how the pick weighs people\npriority: 3 2 1\nopen ask: 1\nshare: 10\nshare since: 2026-12-01\n\n' + FILE
        self.assertEqual(reviewers.settings(text), {'weights': WEIGHTS, 'share_since': reviewers.dt.date(2026, 12, 1)})

    def test_a_missing_or_unreadable_setting_is_named(self):
        with self.assertRaises(ValueError) as raised:
            reviewers.settings('priority: 3 2\nshare: lots\nshare since: 2026-12-01\n## web\nopen ask: 1\n')
        for named in ('line 1: priority: 3 2', 'line 2: share: lots', 'no `open ask:` line', 'no `priority:` line'):
            self.assertIn(named, str(raised.exception))

    def test_a_pinned_heading_names_its_domain_and_comments_are_skipped(self):
        self.assertEqual([(rule['domain'], rule['names']) for rule in RULES if rule['domain'] == 'auth'],
                         [('auth', ['dave', 'Erin'])])


class Domain(unittest.TestCase):
    def test_the_last_matching_pattern_wins(self):
        cases = {'apps/web/src/features/billing/(invoices)/list.ts': 'billing-invoices',
                 'apps/web/src/features/billing/pay.ts': 'billing',
                 'apps/web/src/app/page.tsx': 'web',
                 'packages/billing/src/total.ts': 'billing'}
        for path, expected in cases.items():
            self.assertEqual(reviewers.domain(RULES, path), expected, path)

    def test_a_slash_anchors_a_pattern_and_a_bare_name_matches_at_any_depth(self):
        self.assertEqual(reviewers.domain(RULES, 'AGENTS.md'), 'conventions')
        self.assertEqual(reviewers.domain(RULES, 'packages/billing/AGENTS.md'), 'conventions')
        self.assertEqual(reviewers.domain(RULES, '.agents/skills/a.md'), 'conventions')
        self.assertIsNone(reviewers.domain(RULES, 'docs/.agents/a.md'))

    def test_codeowners_globs_and_inline_comments(self):
        rules = reviewers.parse('## docs\ndocs/* @alice  # only the files directly in docs\n'
                                '## adr\ndocs/**/adr/ @bob\t# tab before the comment\n'
                                '## notes\ndocs/Release\\ Notes/ @carol\n')
        self.assertEqual(reviewers.domain(rules, 'docs/Release Notes/1.0.md'), 'notes')
        self.assertEqual(reviewers.domain(rules, 'docs/intro.md'), 'docs')
        self.assertIsNone(reviewers.domain(rules, 'docs/guides/intro.md'))
        self.assertEqual(reviewers.domain(rules, 'docs/adr/0001.md'), 'adr')
        self.assertEqual(reviewers.domain(rules, 'docs/x/adr/0001.md'), 'adr')
        self.assertEqual(rules[0]['names'], ['alice'])

    def test_unowned_and_unmatched_paths_have_no_domain(self):
        for path in ('docs/adr/0001-totals.md', 'packages/billing/docs/adr/0002.md', 'packages/billing/CONTEXT.md',
                     'README.md', 'package.json'):
            self.assertIsNone(reviewers.domain(RULES, path), path)


class Place(unittest.TestCase):
    def test_a_decision_in_no_domain_takes_the_main_changes(self):
        changed = ['packages/billing/a.ts', 'packages/billing/b.ts', 'packages/auth/c.ts', 'docs/adr/0001.md', 'README.md']
        placed = reviewers.place(RULES, [decision('docs/adr/0001.md:3'), decision('README.md:1', 'D2'),
                                         decision('packages/auth/c.ts:9', 'D3'), decision('', None)], changed)
        self.assertEqual([entry['domain'] for entry in placed], ['billing', 'billing', 'auth', 'billing'])

    def test_a_tie_for_the_main_change_goes_to_the_first_name_and_no_domain_leaves_none(self):
        tie = reviewers.place(RULES, [decision('README.md:1')], ['packages/billing/a.ts', 'packages/auth/b.ts'])
        self.assertEqual(tie[0]['domain'], 'auth')
        self.assertIsNone(reviewers.place(RULES, [decision('README.md:1')], ['README.md'])[0]['domain'])


def standing(asks=None, shares=None, rules=RULES):
    """Everyone the file names, with these open asks and shares, whatever their case, and none otherwise."""
    asks = {login.lower(): count for login, count in (asks or {}).items()}
    shares = {login.lower(): share for login, share in (shares or {}).items()}
    return {login.lower(): {'asks': asks.get(login.lower(), 0), 'share': shares.get(login.lower(), 0.0)}
            for login in reviewers.unique(name for rule in rules for name in rule['names'])}


class Pick(unittest.TestCase):
    def pick(self, *domains, author='zed', engaged=(), load=None, shares=None, held=None, rules=RULES):
        known = standing(load, shares, rules)
        return [(reviewer['login'], reviewer['role'], reviewer['domains']) for reviewer in
                reviewers.pick(rules, [{'domain': name} for name in domains], author, list(engaged), known, WEIGHTS,
                               held or {})]

    def test_the_domain_with_most_decisions_gets_its_p1_and_another_only_where_they_are_not_p1_or_p2(self):
        self.assertEqual(self.pick('auth', 'billing', 'billing', 'conventions'),
                         [('alice', 'P1', ['billing']), ('dave', 'P1', ['auth']), ('bob', 'P1', ['conventions'])])
        # bob is billing's P2, so the first pick covers billing too.
        self.assertEqual(self.pick('conventions', 'conventions', 'billing'), [('bob', 'P1', ['conventions', 'billing'])])

    def test_the_author_is_never_picked(self):
        self.assertEqual(self.pick('billing', author='alice'), [('bob', 'P2', ['billing'])])
        self.assertEqual(self.pick('billing-invoices', author='carol', load={'alice': 2, 'bob': 2, 'dave': 1, 'Erin': 1}),
                         [('dave', 'fallback', ['billing-invoices'])])

    def test_logins_match_whatever_their_case(self):
        self.assertEqual(self.pick('billing', author='Alice'), [('bob', 'P2', ['billing'])])
        self.assertEqual(self.pick('billing', engaged=['Alice']), [])
        twice = reviewers.parse('## billing\n/a/ @Alice\n/b/ @alice @Bob\n')
        self.assertEqual(reviewers.names(twice, 'billing'), ['Alice', 'Bob'])
        self.assertEqual(self.pick('web', load={'Alice': 0, 'BOB': 1, 'carol': 1, 'dave': 1, 'erin': 1}),
                         [('alice', 'fallback', ['web'])])

    def test_someone_already_asked_who_covers_a_domain_adds_nobody(self):
        self.assertEqual(self.pick('billing', engaged=['bob']), [])
        self.assertEqual(self.pick('billing', 'auth', engaged=['bob']), [('dave', 'P1', ['auth'])])
        # A P3 or someone unlisted doesn't cover it.
        self.assertEqual(self.pick('billing', engaged=['carol']), [('alice', 'P1', ['billing'])])

    def test_a_domain_with_nobody_takes_the_least_loaded_person_unless_someone_is_already_asked(self):
        self.assertEqual(self.pick('web', load={'alice': 3, 'bob': 1, 'carol': 1, 'dave': 2, 'Erin': 1}),
                         [('bob', 'fallback', ['web'])])
        self.assertEqual(self.pick('web', 'billing'), [('alice', 'P1', ['billing'])])
        self.assertEqual(self.pick('web', 'web', 'billing'), [('alice', 'P1', ['billing'])])
        self.assertEqual(self.pick(None, engaged=['carol']), [])
        self.assertEqual(self.pick(None, load={'alice': 1, 'bob': 1, 'carol': 1, 'dave': 1}), [('Erin', 'fallback', [])])


class Score(unittest.TestCase):
    """The pick on a real repository's numbers from one day, renamed, on day 1 after `share
    since`: every share 0, and the open asks people hadn't started yet."""
    FILE = ('## bookkeeping\n/packages/bookkeeping/ @ann @owen\n'
            '## transactions\n/packages/transactions/ @lee\n## rpc\n/packages/rpc/ @owen\n'
            '## other\n/packages/other/ @Cass @jo @Cole\n')
    ASKS = {'owen': 3, 'ann': 2, 'Cass': 1, 'jo': 1, 'Cole': 1, 'lee': 0}

    def pick(self, name, asks=None, shares=None):
        rules = reviewers.parse(self.FILE)
        return Pick.pick(Pick(), name, author='someone', load=asks or self.ASKS, shares=shares, rules=rules)

    def test_a_p1_wins_unless_their_open_asks_cancel_their_points(self):
        self.assertEqual(self.pick('bookkeeping'), [('ann', 'P1', ['bookkeeping'])])
        self.assertEqual(self.pick('transactions'), [('lee', 'P1', ['transactions'])])
        # 3 points less 3 open asks ties lee's 0, and the tie goes to fewer open asks.
        self.assertEqual(self.pick('rpc'), [('lee', 'fallback', ['rpc'])])

    def test_a_large_review_share_outweighs_a_p1(self):
        asks = dict.fromkeys(self.ASKS, 0)
        self.assertEqual(self.pick('transactions', asks, {'lee': 0.45}), [('ann', 'fallback', ['transactions'])])
        self.assertEqual(self.pick('transactions', asks, {'lee': 0.2}), [('lee', 'P1', ['transactions'])])

    def test_an_exact_tie_goes_to_fewer_open_asks_whatever_the_float_noise(self):
        # ann: 3 - 1 - 10 * 5/6 and jo: 0 - 3 - 10 * 1/3 are both -19/3, apart only in the last digit.
        asks = {**dict.fromkeys(self.ASKS, 9), 'ann': 1, 'jo': 3}
        self.assertEqual(self.pick('bookkeeping', asks, {'ann': 5 / 6, 'jo': 1 / 3}), [('ann', 'P1', ['bookkeeping'])])

    def test_a_p3_counts_and_a_winner_takes_another_domain_it_wins(self):
        asks = {**dict.fromkeys(self.ASKS, 2), 'Cole': 0, 'owen': 4}
        self.assertEqual(self.pick('other', asks), [('Cole', 'P3', ['other'])])
        rules = reviewers.parse(self.FILE)
        picked = reviewers.pick(rules, [{'domain': 'rpc'}, {'domain': 'other'}], 'someone', [],
                                standing(asks, rules=rules), WEIGHTS, {})
        self.assertEqual([(reviewer['login'], reviewer['domains']) for reviewer in picked], [('Cole', ['other', 'rpc'])])

    def test_whom_an_earlier_handoff_picked_keeps_the_domain_while_they_are_asked(self):
        self.assertEqual(Pick.pick(Pick(), 'billing', engaged=['carol'], held={'billing': 'carol'}), [])
        self.assertEqual(Pick.pick(Pick(), 'billing', held={'billing': 'carol'}), [('alice', 'P1', ['billing'])])


if __name__ == '__main__':
    unittest.main()

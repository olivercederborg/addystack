"""handoff.py against GitHub as `_facts` would read it: when a handoff posts, whom it asks,
what the reviewing agent reads in it, and that the comment goes out before the request."""
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import handoff  # noqa: E402
import reviewers  # noqa: E402

HEAD, BASE = 'a' * 40, 'b' * 40
RULES = reviewers.parse('## billing\n/packages/billing/ @alice @bob\n\n## auth\n/packages/auth/ @dave\n')
DISCLOSURE = '<sub>`AGENT`</sub><br>'
SETTINGS = {'weights': {'P1': 3, 'P2': 2, 'P3': 1, 'open ask': 1, 'share': 10, 'reuse': 2}, 'share_since': None}


def standing(away=(), **asks):
    return {login: {'asks': asks.get(login, 0), 'share': 0.0, 'away': 'no activity since 17 Nov' if login in away else None}
            for login in ('alice', 'bob', 'dave')}


def decision(id_, code, gate='interface', text='Add a totals RPC'):
    return {'id': id_, 'decision': text, 'code': code, 'gate': gate, 'why': 'a new public RPC shape',
            'ask': 'Should totals be a public RPC?'}


def verdict(*decisions):
    return {'pr': 7, 'base': BASE, 'head': HEAD, 'decisions': list(decisions), 'sensitive': []}


class Plan(unittest.TestCase):
    def facts(self, **changes):
        return {'viewer': 'reviewer-app[bot]', 'author': 'carol', 'body': '', 'base': BASE, 'head': HEAD,
                'rules': RULES, 'changed': ['packages/billing/a.ts', 'packages/billing/rpc.ts', 'packages/auth/b.ts', 'docs/adr/1.md'],
                'settings': SETTINGS, 'standing': standing(), 'engaged': [], 'handoffs': [], **changes}

    def plan(self, judged, facts=None, same_diff=True, **options):
        with patch.object(handoff, '_facts', lambda number: facts or self.facts()), \
                patch.object(handoff.gates, 'same_diff', lambda judged_base, base, head: same_diff), \
                patch.object(handoff.gates, 'one_way_doors', lambda base, cwd='.': None):
            return handoff.plan(7, judged, DISCLOSURE, **options)

    def test_a_first_handoff_asks_the_p1_and_gives_the_agent_every_decision_in_full(self):
        drafted = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12'), decision(None, 'docs/adr/1.md:1', 'pattern')))
        self.assertEqual((drafted['post'], drafted['why']), (True, 'first handoff'))
        self.assertEqual(drafted['request'], [{'login': 'alice', 'role': 'P1', 'domains': ['billing']}])
        comment = drafted['comment']
        self.assertTrue(comment.startswith(DISCLOSURE + '\n**Needs a human** · 2 decisions at `aaaaaaa` · asking: `alice`\n'))
        self.assertNotIn('@alice', comment)
        for line in ('### D1 · architectural or interface decision', '- **Decide:** Should totals be a public RPC?',
                     '- **Why a human:** a new public RPC shape', '- **Code:** `packages/billing/rpc.ts:12`',
                     '- **Domain:** `billing` · alice (P1), bob (P2)', '### Not in the Decisions table · new or changed pattern',
                     '- `alice` · P1 · billing'):
            self.assertIn(line, comment)
        block = handoff.read(comment)
        self.assertEqual((block['head'], block['by'], block['chosen_by']), (HEAD, 'reviewer-app[bot]', 'rule'))
        self.assertEqual([(entry['key'], entry['domain']) for entry in block['decisions']],
                         [('D1:interface', 'billing'), ('docs/adr/1.md:pattern', 'billing')])

    def test_its_own_handoff_of_the_same_decisions_is_not_posted_again(self):
        first = handoff.read(self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')))['comment'])
        # Reworded at a new line: still the same decision.
        again = verdict(decision('D1', 'packages/billing/rpc.ts:40', text='Expose totals over RPC'))
        asked = self.plan(again, self.facts(handoffs=[first], engaged=['alice']))
        self.assertEqual((asked['post'], asked['why'], asked['request']), (False, 'nothing new', []))
        # The request failed after the comment posted: the retry asks again and posts nothing.
        retried = self.plan(again, self.facts(handoffs=[first]))
        self.assertEqual((retried['post'], [reviewer['login'] for reviewer in retried['request']]), (False, ['alice']))
        # Meanwhile the P2 reviewed: the domain is covered, so nobody is asked.
        covered = self.plan(again, self.facts(handoffs=[first], engaged=['bob']))
        self.assertEqual((covered['post'], covered['request']), (False, []))

    def test_a_re_review_leaves_a_domain_with_whom_it_picked_even_if_reviewers_does_not_list_them(self):
        busy = standing(alice=4, bob=4)
        first = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')), self.facts(standing=busy))
        self.assertEqual(first['request'], [{'login': 'dave', 'role': 'fallback', 'domains': ['billing']}])
        again = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')),
                          self.facts(standing=busy, handoffs=[handoff.read(first['comment'])], engaged=['dave']))
        self.assertEqual((again['post'], again['request']), (False, []))
        self.assertIn('- `dave` · no priority here, least loaded · billing', first['comment'])
        # A later handoff named alice, but the request to alice failed: dave, still asked, keeps billing.
        later = {**handoff.read(first['comment']), 'reviewers': [{'login': 'alice', 'role': 'chosen', 'domains': ['billing']}]}
        kept = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')),
                         self.facts(standing=busy, handoffs=[handoff.read(first['comment']), later], engaged=['dave']))
        self.assertEqual(kept['request'], [])

    def test_someone_already_asked_who_wins_an_area_keeps_it_on_a_re_review(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @bob\n## pay\n/packages/pay/ @zoe\n## else\n/packages/else/ @amy\n')
        known = {login: {'asks': asks, 'share': 0.0, 'away': None} for login, asks in (('amy', 0), ('bob', 0), ('zoe', 2))}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, engaged=['amy'], changed=['packages/ops/a.ts', 'packages/pay/c.ts'])
        first = self.plan(judged, facts)
        # amy, already asked, takes pay (0 + 2 reuse beats zoe's 3 - 2): only bob is requested.
        self.assertEqual(first['request'], [{'login': 'bob', 'role': 'P1', 'domains': ['ops']}])
        self.assertIn('- `amy` · already asked, keeps these areas · pay', first['comment'])
        self.assertIn('asking: `bob`\n', first['comment'])
        # zoe is free now, but amy, still asked, keeps pay: nobody new is requested.
        again = self.plan(judged, {**facts, 'engaged': ['amy', 'bob'], 'handoffs': [handoff.read(first['comment'])],
                                   'standing': {**known, 'zoe': {'asks': 0, 'share': 0.0, 'away': None}}})
        self.assertEqual((again['post'], again['request']), (False, []))

    def test_areas_the_authors_pick_wins_too_are_kept_on_their_record(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @amy\n## pay\n/packages/pay/ @zoe\n')
        known = {'amy': {'asks': 0, 'share': 0.0, 'away': None}, 'zoe': {'asks': 2, 'share': 0.0, 'away': None}}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, changed=['packages/ops/a.ts', 'packages/pay/c.ts'], viewer='carol')
        first = self.plan(judged, facts, chosen=('amy',), with_suggested=True)
        self.assertEqual(handoff.read(first['comment'])['reviewers'], [{'login': 'amy', 'role': 'chosen', 'domains': ['ops', 'pay']}])
        again = self.plan(judged, {**facts, 'engaged': ['amy'], 'handoffs': [handoff.read(first['comment'])],
                                   'standing': {**known, 'zoe': {'asks': 0, 'share': 0.0, 'away': None}}})
        self.assertEqual(again['request'], [])

    def test_a_re_review_posts_when_someone_already_asked_newly_keeps_an_area(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @bob\n## pay\n/packages/pay/ @zoe\n## else\n/packages/else/ @amy\n')
        known = {login: {'asks': asks, 'share': 0.0, 'away': None} for login, asks in (('amy', 0), ('bob', 0), ('zoe', 2))}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, changed=['packages/ops/a.ts', 'packages/pay/c.ts'],
                           engaged=['amy', 'bob', 'zoe'])
        initial = handoff.read(self.plan(judged, facts)['comment'])
        # zoe's request ended; amy, still asked, now takes pay: that's posted, so it's remembered.
        second = self.plan(judged, {**facts, 'engaged': ['amy', 'bob'], 'handoffs': [initial]})
        self.assertEqual((second['post'], second['why'], second['request']), (True, 'areas changed', []))
        third = self.plan(judged, {**facts, 'engaged': ['amy', 'bob'], 'handoffs': [initial, handoff.read(second['comment'])],
                                   'standing': {**known, 'zoe': {'asks': 0, 'share': 0.0, 'away': None}}})
        self.assertEqual((third['post'], third['request']), (False, []))

    def test_someone_already_named_who_now_holds_more_areas_is_posted(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @bob\n## pay\n/packages/pay/ @zoe\n## else\n/packages/else/ @amy\n')
        known = {login: {'asks': asks, 'share': 0.0, 'away': None} for login, asks in (('amy', 0), ('bob', 0), ('zoe', 2))}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, engaged=['amy'], changed=['packages/ops/a.ts', 'packages/pay/c.ts'])
        block = handoff.read(self.plan(judged, facts)['comment'])
        # Both requests ended and bob is busier: amy, named before for pay, now takes ops too.
        busy = {**known, 'bob': {'asks': 4, 'share': 0.0, 'away': None}}
        second = self.plan(judged, {**facts, 'engaged': [], 'handoffs': [block], 'standing': busy})
        self.assertEqual((second['post'], second['why']), (True, 'new reviewer'))
        third = self.plan(judged, {**facts, 'engaged': ['amy'], 'handoffs': [block, handoff.read(second['comment'])],
                                   'standing': busy})
        self.assertEqual(third['request'], [])

    def test_requesting_someone_who_was_only_kept_before_is_posted(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @bob\n## pay\n/packages/pay/ @zoe\n## else\n/packages/else/ @amy\n')
        known = {login: {'asks': asks, 'share': 0.0, 'away': None} for login, asks in (('amy', 0), ('bob', 0), ('zoe', 2))}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, engaged=['amy'], changed=['packages/ops/a.ts', 'packages/pay/c.ts'])
        block = handoff.read(self.plan(judged, facts)['comment'])
        # amy's request, made by the author, ended unreviewed; with bob and zoe busy amy now
        # wins pay outright, and is newly requested.
        busy = {**known, 'bob': {'asks': 4, 'share': 0.0, 'away': None}, 'zoe': {'asks': 4, 'share': 0.0, 'away': None}}
        again = self.plan(judged, {**facts, 'engaged': ['bob'], 'handoffs': [block], 'standing': busy})
        self.assertEqual((again['post'], again['why'], [r['login'] for r in again['request']]), (True, 'new reviewer', ['amy']))

    def test_with_suggested_keeps_an_area_someone_already_asked_wins(self):
        rules = reviewers.parse('## ops\n/packages/ops/ @bob\n## pay\n/packages/pay/ @zoe\n## else\n/packages/else/ @amy\n')
        known = {login: {'asks': asks, 'share': 0.0, 'away': None} for login, asks in (('amy', 0), ('bob', 0), ('zoe', 2))}
        judged = verdict(decision('D1', 'packages/ops/a.ts:1'), decision('D2', 'packages/ops/b.ts:1'),
                         decision('D3', 'packages/pay/c.ts:1'))
        facts = self.facts(rules=rules, standing=known, engaged=['amy'], viewer='carol',
                           changed=['packages/ops/a.ts', 'packages/pay/c.ts'])
        first = self.plan(judged, facts, chosen=('bob',), with_suggested=True)
        self.assertIn('asking: `bob` · reviewer chosen by the author\n', first['comment'])
        self.assertIn({'login': 'amy', 'role': 'kept', 'domains': ['pay']}, handoff.read(first['comment'])['reviewers'])
        # zoe is free later, but amy, still asked, keeps pay.
        later = self.plan(judged, {**facts, 'engaged': ['amy', 'bob'], 'handoffs': [handoff.read(first['comment'])],
                                   'standing': {**known, 'zoe': {'asks': 0, 'share': 0.0, 'away': None}}}, chosen=('bob',), with_suggested=True)
        self.assertEqual(later['request'], [])

    def test_people_who_are_away_are_skipped_and_named_with_why(self):
        drafted = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')), self.facts(standing=standing(away={'alice'})))
        self.assertEqual(drafted['request'], [{'login': 'bob', 'role': 'P2', 'domains': ['billing']}])
        self.assertIn('- Away, so not asked: `alice` (no activity since 17 Nov)', drafted['comment'])
        self.assertEqual(handoff.read(drafted['comment'])['away'], [{'login': 'alice', 'reason': 'no activity since 17 Nov'}])
        nobody = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')),
                           self.facts(standing=standing(away={'alice', 'bob', 'dave'})))
        self.assertEqual((nobody['why'], nobody['request']), ('nobody to ask', []))
        self.assertIn('- Nobody to ask for `billing`: everyone else REVIEWERS names is away or already asked.',
                      nobody['comment'])
        # alice already covers billing, but nobody is left for auth: the comment says so.
        partly = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12'), decision('D2', 'packages/auth/b.ts:3')),
                           self.facts(engaged=['alice'], standing=standing(away={'bob', 'dave'})))
        self.assertEqual(partly['request'], [])
        self.assertIn('- Nobody to ask for `auth`:', partly['comment'])
        self.assertNotIn('cover these decisions', partly['comment'])
        # The author's own pick is requested, so it isn't listed as away and not asked.
        chosen = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')),
                           self.facts(viewer='carol', standing=standing(away={'alice'})), chosen=('alice',))
        self.assertNotIn('Away, so not asked', chosen['comment'])
        # The PR's author is never listed as away, even when they are.
        own = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')),
                        self.facts(author='dave', standing=standing(away={'dave'})))
        self.assertEqual(handoff.read(own['comment'])['away'], [])
        # With --with-suggested, a domain the suggestion can't fill is named too.
        both = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12'), decision('D2', 'packages/auth/b.ts:3')),
                         self.facts(viewer='carol', standing=standing(away={'bob', 'dave'})), chosen=('alice',),
                         with_suggested=True)
        self.assertEqual(handoff.read(both['comment'])['unfilled'], ['auth'])

    def test_changed_decisions_post_a_new_handoff_and_ask_only_whom_they_need(self):
        first = handoff.read(self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12')))['comment'])
        changed = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12'), decision('D2', 'packages/auth/b.ts:3')),
                            self.facts(handoffs=[first], engaged=['alice']))
        self.assertEqual((changed['post'], changed['why']), (True, 'decisions changed'))
        self.assertEqual([reviewer['login'] for reviewer in changed['request']], ['dave'])
        self.assertIn('- Already asked: `alice`', changed['comment'])

    def test_the_authors_pick_is_requested_and_names_what_it_leaves_uncovered(self):
        judged = verdict(decision('D1', 'packages/billing/rpc.ts:12'), decision('D2', 'packages/auth/b.ts:3'))
        facts = self.facts(viewer='carol')
        drafted = self.plan(judged, facts, chosen=('bob',))
        self.assertEqual(drafted['request'], [{'login': 'bob', 'role': 'chosen', 'domains': ['billing']}])
        self.assertEqual((drafted['uncovered'], [reviewer['login'] for reviewer in drafted['suggested']]),
                         (['auth'], ['dave', 'alice']))
        self.assertIn('· reviewer chosen by the author', drafted['comment'].splitlines()[1])
        self.assertEqual(handoff.read(drafted['comment'])['chosen_by'], 'author')
        both = self.plan(judged, facts, chosen=('bob',), with_suggested=True)
        self.assertEqual([reviewer['login'] for reviewer in both['request']], ['bob', 'dave'])
        with self.assertRaisesRegex(ValueError, 'carol wrote the PR'):
            self.plan(judged, facts, chosen=('carol',))

    def test_the_authors_new_pick_replaces_an_earlier_one_and_nobody_is_asked_twice(self):
        judged = verdict(decision('D1', 'packages/billing/rpc.ts:12'))
        earlier = handoff.read(self.plan(judged, self.facts(viewer='carol'), chosen=('alice',))['comment'])
        switched = self.plan(judged, self.facts(viewer='carol', handoffs=[earlier]), chosen=('bob',))
        self.assertEqual([reviewer['login'] for reviewer in switched['request']], ['bob'])
        reviewed = self.plan(judged, self.facts(viewer='carol', handoffs=[earlier], engaged=['alice']), chosen=('alice',))
        self.assertEqual((reviewed['post'], reviewed['request']), (False, []))
        back = self.plan(judged, self.facts(viewer='carol', handoffs=[earlier]))
        self.assertEqual([reviewer['login'] for reviewer in back['request']], ['alice'])
        bob_first = handoff.read(self.plan(judged, self.facts(viewer='carol'), chosen=('bob',))['comment'])
        to_rule = self.plan(judged, self.facts(viewer='carol', handoffs=[bob_first]))
        self.assertEqual([reviewer['login'] for reviewer in to_rule['request']], ['alice'])

    def test_the_authors_pick_covers_only_its_own_domains(self):
        judged = verdict(decision('D1', 'packages/billing/rpc.ts:12'))
        drafted = self.plan(judged, self.facts(viewer='carol', engaged=['alice']), chosen=('dave',), with_suggested=True)
        self.assertEqual((drafted['uncovered'], drafted['request']),
                         (['billing'], [{'login': 'dave', 'role': 'chosen', 'domains': []}]))

    def test_when_reviewers_names_only_the_author_the_handoff_says_nobody_was_asked(self):
        lonely = self.plan(verdict(decision('D1', 'packages/auth/a.ts:1')), self.facts(author='dave', rules=reviewers.parse(
            '## auth\n/packages/auth/ @dave\n')))
        self.assertEqual((lonely['post'], lonely['why'], lonely['request']), (True, 'nobody to ask', []))
        self.assertIn("- Nobody to ask for `auth`: REVIEWERS names no one but the PR's author", lonely['comment'])
        self.assertIn('· asking: nobody\n', lonely['comment'])

    def test_a_base_without_reviewers_or_a_moved_head_or_base_hands_off_nothing(self):
        judged = verdict(decision('D1', 'packages/billing/rpc.ts:12'))
        self.assertEqual(self.plan(judged, self.facts(rules=None))['post'], False)
        with self.assertRaisesRegex(ValueError, 'but the head is'):
            self.plan(judged, self.facts(head='c' * 40))
        with self.assertRaisesRegex(ValueError, 'not the one the gates judged'):
            self.plan(judged, same_diff=False)

    def test_no_text_in_a_decision_can_close_the_block(self):
        drafted = self.plan(verdict(decision('D1', 'packages/billing/rpc.ts:12', text='Stop at --> and <!-- here')))
        self.assertEqual(handoff.read(drafted['comment'])['decisions'][0]['decision'], 'Stop at --> and <!-- here')
        self.assertIsNone(handoff.read(drafted['comment'].replace('addystack-handoff:v1', 'addystack-handoff:v2')))


class Send(unittest.TestCase):
    def test_the_comment_goes_out_before_the_request_and_nothing_new_writes_nothing(self):
        writes = []
        def github(command, number, *arguments):
            writes.append((command, [pathlib.Path(argument).read_text() if command == 'comment' else argument
                                     for argument in arguments]))
            return 'https://github.com/o/r/pull/7#issuecomment-1\n'
        request = [{'login': 'alice', 'role': 'P1', 'domains': ['billing']}]
        self.assertEqual(handoff.send(7, {'post': True, 'comment': 'hand off', 'request': request}, github),
                         {'comment': 'https://github.com/o/r/pull/7#issuecomment-1', 'requested': ['alice']})
        self.assertEqual(writes, [('comment', ['hand off']), ('request', ['alice'])])
        writes.clear()
        self.assertEqual(handoff.send(7, {'post': False, 'comment': '', 'request': []}, github),
                         {'comment': None, 'requested': []})
        self.assertEqual(writes, [])


class Facts(unittest.TestCase):
    def test_only_its_own_handoffs_count_and_people_already_asked_exclude_the_author(self):
        unreadable = 'A comment without a handoff block.'
        block = '<!-- addystack-handoff:v1\n' + json.dumps({'decisions': [], 'reviewers': []}) + '\n-->'
        answers = {
            'contents': None,
            'requested_reviewers': 'alice\n',
            'reviews': '\n'.join(json.dumps(review) for review in (
                {'type': 'User', 'login': 'carol', 'state': 'APPROVED', 'commit_id': HEAD},
                {'type': 'User', 'login': 'bob', 'state': 'COMMENTED', 'commit_id': HEAD},
                # A review of an earlier head, one dismissed at this head, and an App's: none counts.
                {'type': 'User', 'login': 'dave', 'state': 'APPROVED', 'commit_id': BASE},
                {'type': 'User', 'login': 'erin', 'state': 'DISMISSED', 'commit_id': HEAD},
                {'type': 'Bot', 'login': 'reviewer-app[bot]', 'state': 'COMMENTED', 'commit_id': HEAD})),
            'comments': '\n'.join(json.dumps({'login': login, 'body': body}) for login, body in
                                  (('carol', block), ('reviewer-app[bot]', block), ('reviewer-app[bot]', unreadable))),
            'files': 'packages/billing/a.ts\n',
            # Last: every other path of this PR starts with it.
            'pulls/7': json.dumps({'user': {'login': 'carol'}, 'body': None, 'base': {'sha': BASE}, 'head': {'sha': HEAD}})}
        def gh(*arguments, missing_ok=False):
            path = next(argument for argument in arguments if argument.startswith('repos/'))
            return next(answer for name, answer in answers.items() if name in path.split('/', 3)[-1])
        with patch.object(handoff, '_gh', gh), patch.object(handoff, 'github', lambda command: 'reviewer-app[bot]\n'):
            facts = handoff._facts(7)
        self.assertEqual((facts['author'], facts['rules'], facts['standing'], facts['engaged']),
                         ('carol', None, None, ['alice', 'bob']))
        self.assertEqual(len(facts['handoffs']), 1, "the author's handoff doesn't stand in for the App's own")


if __name__ == '__main__':
    unittest.main()

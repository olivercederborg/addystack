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


def decision(id_, code, gate='interface', text='Add a totals RPC'):
    return {'id': id_, 'decision': text, 'code': code, 'gate': gate, 'why': 'a new public RPC shape',
            'ask': 'Should totals be a public RPC?'}


def verdict(*decisions):
    return {'pr': 7, 'base': BASE, 'head': HEAD, 'decisions': list(decisions), 'sensitive': []}


class Plan(unittest.TestCase):
    def facts(self, **changes):
        return {'viewer': 'reviewer-app[bot]', 'author': 'carol', 'body': '', 'base': BASE, 'head': HEAD,
                'rules': RULES, 'changed': ['packages/billing/a.ts', 'packages/billing/rpc.ts', 'packages/auth/b.ts', 'docs/adr/1.md'],
                'load': {}, 'engaged': [], 'handoffs': [], **changes}

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
        self.assertTrue(comment.startswith(DISCLOSURE + '\n**Needs a human** · 2 decisions at `aaaaaaa` · requested: `alice`\n'))
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
        self.assertIn("- Nobody to ask: REVIEWERS names no one here but the PR's author", lonely['comment'])
        self.assertIn('· requested: nobody\n', lonely['comment'])

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
            'pulls?state=open': 'alice\nalice\nbob\n',
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
        self.assertEqual((facts['author'], facts['rules'], facts['engaged'], facts['load']),
                         ('carol', None, ['alice', 'bob'], {'alice': 2, 'bob': 1}))
        self.assertEqual(len(facts['handoffs']), 1, "the author's handoff doesn't stand in for the App's own")


if __name__ == '__main__':
    unittest.main()

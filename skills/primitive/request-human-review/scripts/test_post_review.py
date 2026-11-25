"""post-review.py against a fake github.sh and PR: one outcome per review, never on a moved
head, an approval only with nothing held, no gate and the required checks passed, and a
standing request for changes dismissed once nothing holds the approval."""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
loader = SourceFileLoader('post_review', str(HERE / 'post-review.py'))
post_review = importlib.util.module_from_spec(importlib.util.spec_from_loader('post_review', loader))
loader.exec_module(post_review)

HEAD, NEWER, BASE = 'a' * 40, 'c' * 40, 'b' * 40
BODY = '| D1 | Add a totals column | 🤖 agent · build | — | — | `db/schema.ts:12` |\n'


class Fake:
    """github.sh and the PR as GitHub would answer them, recording every write."""

    def __init__(self, required='no required checks on main\nrequired: all passed\n', heads=(), viewer='reviewer-app[bot]',
                 active=None, threads=()):
        self.required, self.heads, self.viewer, self.active = required, list(heads), viewer, active
        self.threads = list(threads)
        self.writes, self.commands = [], []

    def github(self, command, *arguments):
        self.commands.append(command)
        if command == 'viewer':
            return self.viewer + '\n'
        if command == 'head':
            return (self.heads.pop(0) if self.heads else HEAD) + '\n'
        if command == 'required':
            return self.required() if callable(self.required) else self.required
        if command == 'reviewed':
            latest = {'id': 50, 'state': 'COMMENTED', 'commit_id': BASE}
            return json.dumps({**latest, 'active': self.active}) + '\n'
        if command == 'threads':
            return ''.join(json.dumps(thread) + '\n' for thread in self.threads)
        files = {}
        for argument in arguments:
            path = pathlib.Path(str(argument))
            if path.suffix in ('.md', '.json') and path.exists():
                files[path.name] = path.read_text()
        self.writes.append((command, [str(argument) for argument in arguments], files))
        return f'https://github.com/o/r/pull/7#{command}\n'


class Post(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        (self.folder / 'BODY.md').write_text('<sub>`AGENT`</sub><br>\nAdds a totals column.\n')
        (self.folder / 'note.md').write_text('Nit: name it total_cents.')
        self.gate(None)

    def gate(self, gate):
        (self.folder / 'GATES.json').write_text(json.dumps({
            'pr': 7, 'base': BASE, 'head': HEAD, 'sensitive': [],
            'decisions': [{'id': 'D1', 'decision': 'Add a totals column', 'code': 'db/schema.ts:12', 'gate': gate,
                           'why': 'a schema change' if gate else 'follows db/schema.ts:4'}]}))

    def post(self, fake, *findings, head=HEAD, wait=0):
        (self.folder / 'REVIEW.json').write_text(json.dumps({'pr': 7, 'head': HEAD, 'gates': 'GATES.json',
                                                              'body': 'BODY.md', 'findings': list(findings)}))
        clock = iter(range(0, 10_000, 60))
        with patch.object(post_review, 'github', fake.github), \
                patch.object(post_review, 'pr', lambda number: {'body': BODY, 'headRefOid': head}):
            outcome = post_review.post(7, self.folder / 'REVIEW.json', wait, now=lambda: next(clock), sleep=lambda s: None)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ['BODY.md', 'GATES.json', 'REVIEW.json', 'note.md'],
                         'post leaves no scratch files beside REVIEW.json')
        return outcome

    def test_a_clear_pr_with_passed_checks_is_approved_with_notes_in_the_body_and_no_inline_comments(self):
        fake = Fake(threads=[{'id': 'T1', 'isResolved': False, 'comments': [{'author': 'reviewer-app'}]},
                             {'id': 'T2', 'isResolved': False, 'comments': [{'author': 'someone'}]},
                             {'id': 'T3', 'isResolved': True, 'comments': [{'author': 'reviewer-app'}]}])
        nit = {'call': 'non-blocking', 'holds': False, 'title': 'name it total_cents',
               'draft': {'path': 'db/schema.ts', 'line': 12, 'body_file': 'note.md'}}
        outcome = self.post(fake, nit)
        self.assertEqual(outcome, {'head': HEAD, 'outcome': 'approved', 'review': 'https://github.com/o/r/pull/7#approve'})
        self.assertEqual([(command, arguments[:1]) for command, arguments, _ in fake.writes], [('approve', ['7']), ('resolve', ['T1'])])
        command, arguments, files = fake.writes[0]
        self.assertEqual(arguments[1:3], [HEAD, ''])
        self.assertIn('- non-blocking: name it total_cents · `db/schema.ts:12`\n  Nit: name it total_cents.', files['body.md'])
        # The required checks, then the head, are the last reads before the approval.
        self.assertEqual(fake.commands[fake.commands.index('approve') - 2:fake.commands.index('approve')], ['required', 'head'])

    def test_a_held_finding_requests_changes_with_its_inline_comment(self):
        bug = {'call': 'blocking', 'holds': True, 'title': 'totals overflow', 'draft':
               {'path': 'db/schema.ts', 'line': 12, 'body_file': 'note.md'}}
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': BASE})
        self.assertEqual(self.post(fake, bug)['outcome'], 'changes-requested')
        self.assertEqual(len(fake.writes), 1, 'its own standing request for changes stays')
        command, arguments, files = fake.writes[0]
        self.assertEqual((command, arguments[3]), ('review', 'REQUEST_CHANGES'))
        drafts = json.loads(next(text for name, text in files.items() if name.endswith('-drafts.json')))
        self.assertEqual(drafts, [bug['draft']])

    def test_a_gate_posts_findings_and_needs_a_human_and_dismisses_a_standing_request_for_changes(self):
        self.gate('interface')
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': BASE},
                    required=lambda: self.fail('a gated PR never reads its checks'))
        question = {'call': 'question', 'holds': False, 'title': 'is the column nullable?'}
        outcome = self.post(fake, question)
        self.assertEqual((outcome['outcome'], outcome['gated']), ('needs-human', ['D1']))
        (command, arguments, files), dismissal = fake.writes
        self.assertEqual((command, arguments[3]), ('review', 'COMMENT'))
        self.assertIn('**Needs a human.**', files['body.md'])
        self.assertIn('- **D1** · architectural or interface decision: Add a totals column', files['body.md'])
        self.assertIn('- question: is the column nullable?', files['body.md'])
        self.assertEqual((dismissal[0], dismissal[1][:2]), ('dismiss', ['7', '41']))

    def test_a_gate_withdraws_the_apps_earlier_approval_and_a_failed_dismissal_posts_nothing(self):
        self.gate('product')
        fake = Fake(active={'id': 40, 'state': 'APPROVED', 'commit_id': BASE})
        self.assertEqual(self.post(fake)['outcome'], 'needs-human')
        self.assertEqual([(command, arguments[:2]) for command, arguments, _ in fake.writes],
                         [('dismiss', ['7', '40']), ('review', ['7', HEAD])])
        denied = Fake(active={'id': 40, 'state': 'APPROVED', 'commit_id': BASE})
        def refuse(command, *arguments):
            if command == 'dismiss':
                raise ValueError('github.sh dismiss failed: HTTP 403')
            return Fake.github(denied, command, *arguments)
        with patch.object(denied, 'github', refuse), self.assertRaisesRegex(ValueError, 'HTTP 403'):
            self.post(denied)
        self.assertEqual(denied.writes, [])

    def test_a_failed_post_keeps_the_request_for_changes_and_a_push_mid_read_posts_nothing(self):
        self.gate('interface')
        failing = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD})
        def refuse(command, *arguments):
            if command == 'review':
                raise ValueError('github.sh review failed: HTTP 422')
            return Fake.github(failing, command, *arguments)
        with patch.object(failing, 'github', refuse), self.assertRaisesRegex(ValueError, 'HTTP 422'):
            self.post(failing)
        self.assertEqual(failing.writes, [], 'the request for changes still blocks the merge')
        # The App's review is read before the head, so a push during that read stops the run.
        racing = Fake(heads=[NEWER], active={'id': 42, 'state': 'APPROVED', 'commit_id': NEWER})
        self.assertEqual(self.post(racing)['outcome'], 'superseded')
        self.assertEqual(racing.writes, [])

    def test_a_push_during_the_checks_read_posts_nothing(self):
        fake = Fake(heads=[NEWER], required='ci\tfail\nrequired: not all passed\n',
                    active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD})
        self.assertEqual(self.post(fake)['outcome'], 'superseded')
        self.assertEqual(fake.writes, [])

    def test_an_approval_resolves_only_the_threads_it_read_and_never_fails_on_them(self):
        fake = Fake(threads=[{'id': 'T1', 'isResolved': False, 'comments': [{'author': 'reviewer-app'}]}])
        def later(command, *arguments):
            result = Fake.github(fake, command, *arguments)
            if command == 'approve':
                fake.threads.append({'id': 'T9', 'isResolved': False, 'comments': [{'author': 'reviewer-app'}]})
            if command == 'resolve':
                raise ValueError('github.sh resolve failed: HTTP 502')
            return result
        with patch.object(fake, 'github', later):
            outcome = self.post(fake)
        self.assertEqual((outcome['outcome'], outcome['unresolved']), ('approved', ['T1']))
        self.assertEqual([arguments for command, arguments, _ in fake.writes if command == 'resolve'], [['T1']])

    def test_a_held_finding_withdraws_an_approval_before_requesting_changes(self):
        bug = {'call': 'blocking', 'holds': True, 'title': 'totals overflow'}
        fake = Fake(active={'id': 40, 'state': 'APPROVED', 'commit_id': HEAD})
        self.assertEqual(self.post(fake, bug)['outcome'], 'changes-requested')
        self.assertEqual([(command, arguments[:2]) for command, arguments, _ in fake.writes][0], ('dismiss', ['7', '40']))

    def test_pending_checks_are_waited_on_then_approved(self):
        answers = iter(['ci\tpending\nrequired: not all passed\n', 'ci\tpass\nrequired: all passed\n'])
        outcome = self.post(Fake(required=lambda: next(answers)), wait=600)
        self.assertEqual(outcome['outcome'], 'approved')

    def test_checks_that_fail_or_never_finish_are_not_approved(self):
        failed = self.post(Fake(required='ci\tfail\nrequired: not all passed\n'), wait=600)
        self.assertEqual((failed['outcome'], failed['checks']), ('not-approved', ['ci\tfail']))
        slow = Fake(required='ci\tpending\nrequired: not all passed\n')
        outcome = self.post(slow, wait=120)
        self.assertEqual(outcome['outcome'], 'not-approved')
        self.assertIn('ci\tpending', slow.writes[0][2]['body.md'])

    def test_checks_it_cannot_read_never_approve(self):
        def unreadable():
            raise ValueError('github.sh required failed: Resource not accessible by integration')
        outcome = self.post(Fake(required=unreadable))
        self.assertEqual(outcome['outcome'], 'not-approved')
        self.assertIn('Resource not accessible by integration', outcome['checks'][0])

    def test_an_error_leaves_out_ghs_hint_block(self):
        hinted = ('hint: if you need to wait for this pull request to be reviewed, use this instead of polling:\n'
                  '    gh event listen --resource https://github.com/o/r/pull/7\n'
                  '  - It prints the first event as a JSON line on stdout and exits.\n'
                  'GraphQL: Resource not accessible by integration (repository.pullRequest.commits)\n')
        self.assertEqual(post_review._error(hinted), 'GraphQL: Resource not accessible by integration (repository.pullRequest.commits)')

    def test_a_moved_head_posts_nothing(self):
        self.assertEqual(self.post(Fake(), head=NEWER), {'outcome': 'superseded', 'head': NEWER})
        for heads, wait in (([NEWER], 600), ([NEWER], 0)):
            fake = Fake(heads=heads, required='ci\tpending\nrequired: not all passed\n' if wait else
                        'no required checks on main\nrequired: all passed\n')
            self.assertEqual(self.post(fake, wait=wait)['outcome'], 'superseded')
            self.assertEqual(fake.writes, [])

    def test_a_person_never_posts_through_it(self):
        with self.assertRaisesRegex(ValueError, 'posts only as an App'):
            self.post(Fake(viewer='a-person'))

    def test_a_verdict_missing_a_table_row_is_refused(self):
        (self.folder / 'GATES.json').write_text(json.dumps({'pr': 7, 'base': BASE, 'head': HEAD, 'sensitive': [], 'decisions': []}))
        with self.assertRaisesRegex(ValueError, 'D1 from the Decisions table has no entry'):
            self.post(Fake())


if __name__ == '__main__':
    unittest.main()

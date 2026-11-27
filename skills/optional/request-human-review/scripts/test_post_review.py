"""post-review.py against a fake github.sh and PR: one outcome per review, never on a moved
head, an approval only with nothing held, no gate and the required checks passed, and a
standing request for changes dismissed once nothing holds the approval."""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import subprocess
import pathlib
import tempfile
import unittest
from unittest.mock import ANY, patch

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
        # github.sh prints its inline comments' anchors before the posted review's URL.
        return f'db/schema.ts:12 (changed)\nhttps://github.com/o/r/pull/7#{command}\n'


class Post(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        (self.folder / 'BODY.md').write_text('<sub>`AGENT`</sub><br>\nAdds a totals column.\n')
        (self.folder / 'note.md').write_text('Nit: name it total_cents.')
        self.gate(None)
        self.doors = {}
        doors = patch.object(post_review.gates, 'one_way_doors', lambda base, cwd: self.doors.get(base))
        doors.start()
        self.addCleanup(doors.stop)

    def gate(self, gate):
        (self.folder / 'GATES.json').write_text(json.dumps({
            'pr': 7, 'base': BASE, 'head': HEAD, 'sensitive': [],
            'decisions': [{'id': 'D1', 'decision': 'Add a totals column', 'code': 'db/schema.ts:12', 'gate': gate,
                           'why': 'a schema change' if gate else 'follows db/schema.ts:4',
                           **({'ask': 'Ship the totals column?'} if gate else {})}]}))

    def post(self, fake, *findings, head=HEAD, wait=0, second_opinion=None, base=BASE, diffs=None, retry=False, bases=None):
        review = {'pr': 7, 'head': HEAD, 'gates': 'GATES.json', 'body': 'BODY.md', 'findings': list(findings),
                  'second_opinion': {'status': 'ran'} if second_opinion is None else second_opinion}
        if second_opinion == 'absent':
            del review['second_opinion']
        (self.folder / 'REVIEW.json').write_text(json.dumps(review))
        clock = iter(range(0, 10_000, 60))
        diffs = diffs or {}
        if not retry:
            # Each review writes its files in a folder of its own; only a retry of the same one keeps its record.
            (self.folder / 'POSTED.json').unlink(missing_ok=True)
        bases = [entry if isinstance(entry, tuple) else ('main', entry) for entry in (bases or [base])]
        def pr(number, fields=''):
            name, oid = bases.pop(0) if len(bases) > 1 else bases[0]
            return {'body': BODY, 'headRefOid': head, 'baseRefName': name, 'baseRefOid': oid}
        def facts(number):
            # GitHub as the handoff reads it: the fake's own earlier handoffs and requests count.
            writes = [(command, arguments, files) for command, arguments, files in fake.writes]
            return {'viewer': fake.viewer, 'author': 'carol', 'body': BODY, 'base': base, 'head': head,
                    'rules': post_review.handoff.reviewers.parse('## db\n/db/ @alice @bob\n'),
                    'changed': ['db/schema.ts', 'README.md'],
                    'settings': {'weights': {'P1': 3, 'P2': 2, 'P3': 1, 'open ask': 1, 'share': 10}, 'share_since': None},
                    'standing': {login: {'asks': 0, 'share': 0.0} for login in ('alice', 'bob')},
                    'engaged': [login for command, arguments, _ in writes if command == 'request' for login in arguments[1:]],
                    'handoffs': [post_review.handoff.read(files['handoff.md']) for command, _, files in writes
                                 if command == 'comment']}
        with patch.object(post_review, 'github', fake.github), \
                patch.object(post_review.handoff, '_facts', facts), \
                patch.object(post_review.gates, 'same_diff',
                             lambda judged, against, commit: diffs.get(against, 'same') == diffs.get(judged, 'same')), \
                patch.object(post_review, 'pr', pr):
            outcome = post_review.post(7, self.folder / 'REVIEW.json', wait, now=lambda: next(clock), sleep=lambda s: None)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir() if path.name != 'POSTED.json'),
                         ['BODY.md', 'GATES.json', 'REVIEW.json', 'note.md'], 'post leaves no scratch files beside REVIEW.json')
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

    def test_a_finding_without_a_true_or_false_holds_or_a_blocking_one_that_doesnt_hold_posts_nothing(self):
        for finding in ({'call': 'blocking', 'holds': None, 'title': 'totals overflow'},
                        {'call': 'non-blocking', 'title': 'name it total_cents'},
                        {'call': 'blocking', 'holds': False, 'title': 'totals overflow'}):
            fake = Fake()
            with self.subTest(finding), self.assertRaisesRegex(ValueError, 'holds is true or false'):
                self.post(fake, finding)
            self.assertEqual(fake.writes, [])

    def test_a_new_review_of_an_approved_head_says_the_approval_stands_without_approving_again(self):
        # The author asked for a review again, or the PR moved to another base branch: the
        # review still approves, and the author sees that in a comment, not a second approval.
        for event, bases in (('the author asked again', None), ('the PR moved to release', [('release', BASE)])):
            with self.subTest(event):
                fake = Fake(active={'id': 61, 'state': 'APPROVED', 'commit_id': HEAD})
                outcome = self.post(fake, bases=bases)
                self.assertEqual((outcome['outcome'], outcome['review']), ('approved', 'https://github.com/o/r/pull/7#comment'))
                (command, arguments, files), = fake.writes
                self.assertEqual((command, arguments[0]), ('comment', '7'))
                self.assertIn('Adds a totals column.', files['body.md'])
                self.assertIn(f"this App's approval of `{HEAD[:7]}` stands", files['body.md'])
        # An approval of an older head doesn't approve this one.
        older = Fake(active={'id': 61, 'state': 'APPROVED', 'commit_id': BASE})
        self.assertEqual(self.post(older)['review'], 'https://github.com/o/r/pull/7#approve')
        self.assertEqual([command for command, _, _ in older.writes], ['approve'])

    def test_a_retry_of_a_run_that_approved_or_said_so_posts_nothing(self):
        for active in (None, {'id': 61, 'state': 'APPROVED', 'commit_id': HEAD}):
            with self.subTest(active=active):
                fake = Fake(active=active)
                first = self.post(fake)
                # The first run's approval now stands, and the run stopped before it printed its outcome.
                fake.active = active or {'id': 62, 'state': 'APPROVED', 'commit_id': HEAD}
                self.assertEqual(self.post(fake, retry=True), first)
                self.assertEqual(len(fake.writes), 1)
        # A retry that would post another body is a new answer, and says the approval stands.
        fake = Fake()
        self.post(fake)
        fake.active = {'id': 62, 'state': 'APPROVED', 'commit_id': HEAD}
        (self.folder / 'BODY.md').write_text('<sub>`AGENT`</sub><br>\nAdds a totals column; re-read after the rebase.\n')
        self.post(fake, retry=True)
        self.assertEqual([command for command, _, _ in fake.writes], ['approve', 'comment'])
        # A record alone never claims an approval: once a newer review replaced it, a retry approves again.
        replaced = Fake()
        self.post(replaced)
        replaced.active = {'id': 63, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD}
        self.assertEqual(self.post(replaced, retry=True)['review'], 'https://github.com/o/r/pull/7#approve')
        self.assertEqual([command for command, _, _ in replaced.writes], ['approve', 'approve'])

    def test_a_record_of_another_head_or_outcome_is_not_reused(self):
        sent = post_review.hashlib.sha256((self.folder / 'BODY.md').read_text().encode()).hexdigest()
        for record in ({'head': BASE, 'outcome': 'approved'}, {'head': HEAD, 'outcome': 'needs-human'}):
            with self.subTest(record):
                (self.folder / 'POSTED.json').write_text(json.dumps({**record, 'sent': sent, 'review': 'earlier'}))
                fake = Fake(active={'id': 61, 'state': 'APPROVED', 'commit_id': HEAD})
                self.assertEqual(self.post(fake, retry=True)['review'], 'https://github.com/o/r/pull/7#comment')
                self.assertEqual([command for command, _, _ in fake.writes], ['comment'])

    def test_a_held_finding_requests_changes_with_its_inline_comment(self):
        bug = {'call': 'blocking', 'holds': True, 'title': 'totals overflow', 'draft':
               {'path': 'db/schema.ts', 'line': 12, 'body_file': 'note.md'}}
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': BASE})
        outcome = self.post(fake, bug)
        # The posted review's URL, without the anchors github.sh prints before it.
        self.assertEqual((outcome['outcome'], outcome['review']), ('changes-requested', 'https://github.com/o/r/pull/7#review'))
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
        (command, arguments, files), dismissal, handoff, request = fake.writes
        self.assertEqual((command, arguments[3]), ('review', 'COMMENT'))
        self.assertEqual((handoff[0], request[0]), ('comment', 'request'), 'the handoff follows the review')
        self.assertIn('**Needs a human.**', files['body.md'])
        self.assertIn('- **D1** · architectural or interface decision: Add a totals column', files['body.md'])
        self.assertIn('- question: is the column nullable?', files['body.md'])
        self.assertEqual((dismissal[0], dismissal[1][:2]), ('dismiss', ['7', '41']))

    def test_a_refused_request_is_named_in_the_outcome_and_the_review_stands(self):
        self.gate('interface')
        fake = Fake()
        def refuse(command, *arguments):
            if command == 'request':
                raise ValueError('github.sh request failed: HTTP 422 Reviews may only be requested from collaborators')
            return Fake.github(fake, command, *arguments)
        with patch.object(fake, 'github', refuse):
            outcome = self.post(fake)
        self.assertEqual((outcome['outcome'], outcome['handoff']),
                         ('needs-human', {'failed': 'github.sh request failed: HTTP 422 Reviews may only be requested '
                                                    'from collaborators'}))
        self.assertEqual([command for command, _, _ in fake.writes], ['review', 'comment'])
        timing_out = Fake()
        def stall(command, *arguments):
            if command == 'request':
                raise subprocess.TimeoutExpired('gh', 300)
            return Fake.github(timing_out, command, *arguments)
        with patch.object(timing_out, 'github', stall):
            self.assertIn('timed out', self.post(timing_out)['handoff']['failed'])

    def test_a_held_finding_on_a_gated_pr_goes_back_to_the_author_and_asks_nobody(self):
        self.gate('one-way-door')
        fake = Fake()
        bug = {'call': 'blocking', 'holds': True, 'title': 'totals drop refunds'}
        self.assertEqual(self.post(fake, bug)['outcome'], 'changes-requested')
        self.assertEqual([command for command, _, _ in fake.writes], ['review'])

    def test_a_gate_withdraws_the_apps_earlier_approval_and_a_failed_dismissal_posts_nothing(self):
        self.gate('product')
        fake = Fake(active={'id': 40, 'state': 'APPROVED', 'commit_id': BASE})
        self.assertEqual(self.post(fake)['outcome'], 'needs-human')
        self.assertEqual([(command, arguments[:2]) for command, arguments, _ in fake.writes],
                         [('dismiss', ['7', '40']), ('review', ['7', HEAD]), ('comment', ['7', ANY]),
                          ('request', ['7', 'alice'])])
        denied = Fake(active={'id': 40, 'state': 'APPROVED', 'commit_id': BASE})
        def refuse(command, *arguments):
            if command == 'dismiss':
                raise ValueError('github.sh dismiss failed: HTTP 403')
            return Fake.github(denied, command, *arguments)
        with patch.object(denied, 'github', refuse), self.assertRaisesRegex(ValueError, 'HTTP 403'):
            self.post(denied)
        self.assertEqual(denied.writes, [])

    def test_another_prs_verdict_or_a_diff_from_another_base_posts_nothing(self):
        fake = Fake()
        gates_json = json.loads((self.folder / 'GATES.json').read_text())
        (self.folder / 'GATES.json').write_text(json.dumps({**gates_json, 'pr': 8}))
        with self.assertRaisesRegex(ValueError, 'the verdict is for #8, not #7'):
            self.post(fake)
        self.gate(None)
        # Moved to another base: the same head's diff against it isn't the one the gates judged,
        # before the checks are waited on or while they are.
        with self.assertRaisesRegex(ValueError, "not the one the gates judged"):
            self.post(fake, base=NEWER, diffs={NEWER: 'more'})
        with self.assertRaisesRegex(ValueError, 'changed while the checks were waited on'):
            self.post(fake, bases=[BASE, NEWER], diffs={NEWER: 'more'})
        # A base that only moved on leaves the diff, and the run goes on; another branch, even at
        # the same commit, has other required checks, and its retarget starts its own review.
        self.assertEqual(self.post(Fake(), bases=[BASE, NEWER])['outcome'], 'approved')
        self.assertEqual(self.post(fake, bases=[('main', BASE), ('release', BASE)]),
                         {'outcome': 'superseded', 'head': HEAD, 'base': 'release'})
        self.assertEqual(fake.writes, [])

    def test_a_retry_after_a_failed_withdrawal_posts_the_review_once(self):
        self.gate('interface')
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD})
        def dismissal_fails(command, *arguments):
            if command == 'dismiss':
                raise ValueError('github.sh dismiss failed: HTTP 502')
            return Fake.github(fake, command, *arguments)
        with patch.object(fake, 'github', dismissal_fails), self.assertRaisesRegex(ValueError, 'HTTP 502'):
            self.post(fake)
        outcome = self.post(fake, retry=True)
        self.assertEqual(outcome['outcome'], 'needs-human')
        self.assertEqual([command for command, _, _ in fake.writes], ['review', 'dismiss', 'comment', 'request'])

    def test_a_retry_leaves_a_newer_request_for_changes_and_posts_changed_evidence_again(self):
        self.gate('interface')
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD})
        def dismissal_fails(command, *arguments):
            if command == 'dismiss':
                raise ValueError('github.sh dismiss failed: HTTP 502')
            return Fake.github(fake, command, *arguments)
        with patch.object(fake, 'github', dismissal_fails), self.assertRaisesRegex(ValueError, 'HTTP 502'):
            self.post(fake)
        # Another review of this head requested changes meanwhile: the retry leaves that one,
        # whether it reuses its post or, with changed findings, posts again.
        fake.active = {'id': 42, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD}
        self.post(fake, retry=True)
        self.assertEqual([command for command, _, _ in fake.writes], ['review', 'comment', 'request'])
        (self.folder / 'note.md').write_text('Nit: name it total_amount_cents.')
        self.post(fake, {'holds': False, 'draft': {'path': 'a.ts', 'line': 1, 'body_file': 'note.md'}}, retry=True)
        # The same decisions, with the reviewer already asked: no second handoff.
        self.assertEqual([command for command, _, _ in fake.writes], ['review', 'comment', 'request', 'review'])
        # What it would post changed, as a check that went from pending to failed does: it posts again.
        self.gate(None)
        checks = Fake(required='ci\tpending\nrequired: not all passed\n')
        self.assertEqual(self.post(checks)['outcome'], 'not-approved')
        checks.required = 'ci\tfail\nrequired: not all passed\n'
        retried = self.post(checks, retry=True)
        self.assertEqual(retried['checks'], ['ci\tfail'])
        self.assertEqual([command for command, _, _ in checks.writes], ['review', 'review'])
        self.assertIn('ci\tfail', checks.writes[-1][2]['body.md'])

    def test_a_retry_posts_again_when_only_an_inline_comments_text_changed(self):
        self.gate('interface')
        finding = {'holds': False, 'draft': {'path': 'a.ts', 'line': 1, 'body_file': 'note.md'}}
        fake = Fake(active={'id': 41, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD})
        def dismissal_fails(command, *arguments):
            if command == 'dismiss':
                raise ValueError('github.sh dismiss failed: HTTP 502')
            return Fake.github(fake, command, *arguments)
        with patch.object(fake, 'github', dismissal_fails), self.assertRaisesRegex(ValueError, 'HTTP 502'):
            self.post(fake, finding)
        (self.folder / 'note.md').write_text('Nit: the column holds cents; name it total_cents.')
        self.post(fake, finding, retry=True)
        self.assertEqual([command for command, _, _ in fake.writes], ['review', 'review', 'dismiss', 'comment', 'request'])

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

    def test_a_review_without_its_second_opinion_goes_to_a_person_and_says_why(self):
        for second, why in (({'status': 'missing', 'why': 'Codex is not signed in'}, 'Codex is not signed in'),
                            ('absent', "the review didn't say whether it ran")):
            with self.subTest(second=second):
                fake = Fake(required=lambda: self.fail("a review that can't approve never reads its checks"))
                outcome = self.post(fake, second_opinion=second)
                self.assertEqual((outcome['outcome'], outcome['gated']), ('needs-human', ['second opinion']))
                (command, arguments, files), handoff, request = fake.writes
                self.assertEqual((command, arguments[3]), ('review', 'COMMENT'))
                self.assertIn(f'"second_opinion": "{why}"', handoff[2]['handoff.md'])
                self.assertEqual(request[1], ['7', 'alice'], 'the main change\'s P1 reviews in its place')
                self.assertIn(f"- **Second opinion** · the other provider's review didn't run ({why})", files['body.md'])

    def test_a_diff_that_needs_no_second_opinion_is_approved_as_before(self):
        self.assertEqual(self.post(Fake(), second_opinion={'status': 'not-needed'})['outcome'], 'approved')

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
        failed = lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 1, '', hinted)
        with patch.object(post_review.subprocess, 'run', failed):
            for call, prefix in ((lambda: post_review.pr(7), 'gh pr view 7 failed: '),
                                 (lambda: post_review.github('required', 7), 'github.sh required failed: ')):
                with self.assertRaises(ValueError) as raised:
                    call()
                self.assertEqual(str(raised.exception),
                                 prefix + 'GraphQL: Resource not accessible by integration (repository.pullRequest.commits)')

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

    def test_a_sensitive_area_the_repos_one_way_doors_name_is_refused_without_its_gate(self):
        gates_json = json.loads((self.folder / 'GATES.json').read_text())
        (self.folder / 'GATES.json').write_text(json.dumps({
            **gates_json, 'sensitive': [{'area': 'money-movement', 'code': 'db/schema.ts:12'}]}))
        listed = ('.github/PULL_REQUEST_TEMPLATE.md:36', 'money movement, and writes to providers')
        fake = Fake()
        self.doors = {BASE: listed}
        with self.assertRaisesRegex(ValueError, 'money-movement at db/schema.ts:12 is a one-way door'):
            self.post(fake)
        # The list is read at the PR's base now, also when the base moves on while checks are waited on.
        self.doors = {NEWER: listed}
        with self.assertRaisesRegex(ValueError, 'money-movement at db/schema.ts:12 is a one-way door'):
            self.post(fake, base=NEWER)
        with self.assertRaisesRegex(ValueError, 'money-movement at db/schema.ts:12 is a one-way door'):
            self.post(fake, bases=[BASE, NEWER])
        self.assertEqual(fake.writes, [])


if __name__ == '__main__':
    unittest.main()

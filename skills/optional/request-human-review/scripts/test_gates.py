"""gates.py: the GATES.json shape, its coverage of the PR's Decisions table, and the rule an
unattended reviewer follows."""
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gates  # noqa: E402

HEAD, BASE = 'a' * 40, 'b' * 40
BODY = """## Review guide

**Decisions.** D1–D2

| # | Decision | Decided by | Instead of | Assumes | Code |
|---|---|---|---|---|---|
| D1 | Store totals in cents | 🧑 human · plan | floats | — | `db/schema.ts:12` |
| D2 | Reuse the export query | 🤖 agent · build | a new query | — | `export.ts:4` |
"""


def verdict(*decisions, sensitive=()):
    return {'pr': 7, 'base': BASE, 'head': HEAD, 'decisions': list(decisions), 'sensitive': list(sensitive)}


def decision(id_, gate=None, code='a.ts:1'):
    return {'id': id_, 'decision': f'{id_ or "found"} call', 'code': code, 'gate': gate,
            'why': 'adds a column' if gate else 'follows export.ts:9', **({'ask': 'Keep the column?'} if gate else {})}


class Load(unittest.TestCase):
    def write(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = pathlib.Path(folder.name) / 'GATES.json'
        path.write_text(json.dumps(data))
        return path

    def test_a_well_formed_verdict_loads(self):
        data = verdict(decision('D1', 'interface'), decision(None), sensitive=[{'area': 'money-movement', 'code': 'pay.ts:3'}])
        self.assertEqual(gates.load(self.write(data)), data)

    def test_every_shape_problem_is_named(self):
        bad = verdict({'id': 'D1', 'decision': '', 'code': 'a.ts:1', 'gate': 'risky', 'why': 'x'},
                      sensitive=[{'area': 'payments', 'code': 'p.ts:1'}])
        bad['head'] = 'abc'
        with self.assertRaises(ValueError) as raised:
            gates.load(self.write(bad))
        for named in ('head is not a full commit SHA', "D1: gate 'risky'", 'D1: decision is empty', 'D1: ask is empty',
                      "'payments'"):
            self.assertIn(named, str(raised.exception))


class Check(unittest.TestCase):
    def test_every_table_row_needs_an_entry_and_the_head_must_be_current(self):
        self.assertEqual(gates.check(verdict(decision('D1', 'interface'), decision('D2')), BODY, HEAD), [])
        self.assertEqual(gates.check(verdict(decision('D1', 'interface'), decision(None)), BODY, BASE),
                         [f'the verdict judged {HEAD}, but the head is {BASE}', 'D2 from the Decisions table has no entry'])

    def test_a_pr_without_a_table_needs_only_what_the_diff_shows(self):
        self.assertEqual(gates.check(verdict(), '**Decisions.** N/A', HEAD), [])


class Decide(unittest.TestCase):
    def test_a_held_finding_requests_changes_whatever_else_holds(self):
        for gated in (verdict(), verdict(decision('D1', 'one-way-door'))):
            for required in gates.REQUIRED:
                self.assertEqual(gates.decide(gated, True, required, 'ran'), 'request-changes')

    def test_a_gate_needs_a_human_whatever_the_checks(self):
        for required in gates.REQUIRED:
            self.assertEqual(gates.decide(verdict(decision('D1', 'product'), decision('D2')), False, required, 'ran'),
                             'needs-human')

    def test_with_no_gate_the_required_checks_on_the_head_decide(self):
        clear = verdict(decision('D2'), sensitive=[{'area': 'auth', 'code': 'auth.ts:1'}])
        self.assertEqual([gates.decide(clear, False, required, 'ran') for required in gates.REQUIRED],
                         ['approve', 'wait', 'not-approved'])

    def test_a_missing_second_opinion_never_approves_and_a_diff_without_behavior_is_unaffected(self):
        clear = verdict(decision('D2'))
        self.assertEqual(gates.decide(clear, False, 'passed', 'ran'), 'approve')
        self.assertEqual(gates.decide(clear, False, 'passed', 'not-needed'), 'approve')
        for required in gates.REQUIRED:
            self.assertEqual(gates.decide(clear, False, required, 'missing'), 'needs-human')
        self.assertEqual(gates.decide(clear, True, 'passed', 'missing'), 'request-changes')
        with self.assertRaises(ValueError):
            gates.decide(clear, False, 'passed', 'skipped')
        text = gates.section(clear, 'Codex is not signed in')
        self.assertIn('**Needs a human.** A person approves this PR:', text)
        self.assertIn("- **Second opinion** · the other provider's review didn't run (Codex is not signed in)", text)

    def test_section_names_each_gated_decision_with_its_gate_and_code(self):
        text = gates.section(verdict(decision('D1', 'interface', 'db/schema.ts:12'), decision(None, 'pattern'), decision('D2')))
        self.assertIn('- **D1** · architectural or interface decision: D1 call · `db/schema.ts:12` · adds a column', text)
        self.assertIn('- **Not in the Decisions table** · new or changed pattern: found call', text)
        self.assertNotIn('D2', text)


class OneWayDoors(unittest.TestCase):
    """The repository's own one-way doors, read from its PR template at the base, gate a sensitive
    area they name even when its change follows a pattern."""

    TEMPLATE = ('## Risk\n\n<!-- A one-way door is not cheap to reverse. One-way doors include migrations that drop '
                'data, removed or changed public API, RPC, or event fields, money movement, and writes to providers. '
                'When unsure, call it one-way. -->\n')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = pathlib.Path(folder.name)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.repo)], check=True)

    def base(self, files):
        for path, text in files.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text)
        run = lambda *arguments: subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c',
                                                 'user.email=t@example.com', *arguments], capture_output=True,
                                                text=True, check=True).stdout
        run('add', '-A')
        run('commit', '-q', '--allow-empty', '-m', 'base')
        return run('rev-parse', 'HEAD').strip()

    def problems(self, gated_verdict, files):
        return gates.doors(gated_verdict, self.base(files), str(self.repo))

    def test_a_money_movement_change_that_follows_a_pattern_needs_a_human_where_the_template_lists_it(self):
        paying = verdict(decision(None, code='pay.ts:3'), sensitive=[{'area': 'money-movement', 'code': 'pay.ts:3'}])
        self.assertEqual(self.problems(paying, {'.github/PULL_REQUEST_TEMPLATE.md': self.TEMPLATE}),
                         ['money-movement at pay.ts:3 is a one-way door by .github/PULL_REQUEST_TEMPLATE.md:3: it needs '
                          'a one-way-door decision at that code'])
        gated = verdict(decision(None, 'one-way-door', 'pay.ts:3'), sensitive=paying['sensitive'])
        self.assertEqual(self.problems(gated, {}), [])
        self.assertEqual(gates.decide(gated, False, 'passed', 'ran'), 'needs-human')

    def test_a_repo_without_such_a_list_keeps_sensitive_areas_for_blast_radius_only(self):
        paying = verdict(decision(None), sensitive=[{'area': 'money-movement', 'code': 'pay.ts:3'},
                                                    {'area': 'auth', 'code': 'auth.ts:1'}])
        for files in ({}, {'.github/pull_request_template.md': '## Risk\n\nSay what could break.\n'}):
            self.assertEqual(self.problems(paying, files), [])
        self.assertEqual(gates.decide(paying, False, 'passed', 'ran'), 'approve')
        # A list that names other kinds leaves these areas alone.
        self.assertEqual(self.problems(paying, {'docs/pull_request_template.md': 'One-way doors include sent emails.\n'}),
                         [])

    def test_only_the_template_github_uses_counts(self):
        self.base({'docs/PULL_REQUEST_TEMPLATE.md': 'One-way doors include auth.\n',
                   'PULL_REQUEST_TEMPLATE.md': 'One-way doors include money movement.\n'})
        self.assertEqual(gates.one_way_doors('HEAD', str(self.repo)), ('PULL_REQUEST_TEMPLATE.md:1', 'money movement'))
        # A .github/ template shadows the root's, even when it lists none.
        self.base({'.github/pull_request_template.md': '## Risk\n'})
        self.assertIsNone(gates.one_way_doors('HEAD', str(self.repo)))

    def test_the_list_is_read_whole_and_ends_where_it_does(self):
        sensitive = verdict(sensitive=[{'area': 'money-movement', 'code': 'pay.ts:3'},
                                       {'area': 'auth', 'code': 'auth.ts:1'}])
        def named(template):
            return [problem.split(' is ')[0] for problem in self.problems(sensitive, {'PULL_REQUEST_TEMPLATE.md': template})]
        # Wrapped across lines, after another sentence about one-way doors.
        self.assertEqual(named('One-way doors are hard to reverse. One-way doors\ninclude sent emails and money\nmovement.\n'),
                         ['money-movement at pay.ts:3'])
        # A list without its period stops at the blank line or the comment's end.
        self.assertEqual(named('One-way doors include money movement\n\n## Auth\n'), ['money-movement at pay.ts:3'])
        self.assertEqual(named('<!-- One-way doors include money movement --> auth\n'), ['money-movement at pay.ts:3'])
        self.assertEqual(named('One-way doors include sent emails\n## Auth\n'), [])
        self.assertEqual(named('One-way doors include money movement\n\nauth\n'), ['money-movement at pay.ts:3'])
        # Only an item that is an area's own name counts, in either spelling; a narrower one is the agent's to gate.
        self.assertEqual(named('One-way doors include authorization changes, or changes to money movement limits.\n'), [])
        self.assertEqual(named('One-way doors include auth or money-movement.\n'), ['money-movement at pay.ts:3', 'auth at auth.ts:1'])
        # Markdown marks, an aside in parentheses, and semicolons leave an item its name.
        for template in ('One-way doors include **money movement**, migrations.\n',
                         'One-way doors include `money movement` and migrations.\n',
                         'One-way doors include money movement (payouts, transfers), and migrations.\n',
                         'One-way doors include migrations; money movement; sent emails.\n'):
            self.assertEqual(named(template), ['money-movement at pay.ts:3'], template)
        # Known limits, left to the agent: "e.g." ends the sentence, and a bulleted list reads as one item.
        self.assertEqual(named('One-way doors include e.g. money movement and migrations.\n'), [])
        self.assertEqual(named('One-way doors include:\n- money movement\n- migrations\n'), [])
        self.assertIn('by PULL_REQUEST_TEMPLATE.md:2:', self.problems(sensitive, {'PULL_REQUEST_TEMPLATE.md':
                                                                                   '# PR\nOne-way doors include auth.\n'})[0])

    def test_a_review_in_a_subfolder_reads_the_repository_s_template(self):
        base = self.base({'.github/PULL_REQUEST_TEMPLATE.md': self.TEMPLATE, 'src/pay.ts': ''})
        self.assertEqual(gates.one_way_doors(base, str(self.repo / 'src'))[0], '.github/PULL_REQUEST_TEMPLATE.md:3')

    def test_a_base_the_checkout_lacks_fails_loudly(self):
        self.base({})
        with self.assertRaises(subprocess.CalledProcessError):
            gates.one_way_doors(BASE, str(self.repo))


class OwnDiff(unittest.TestCase):
    """The PR's own diff after a rebase: unchanged when only the base moved, changed by a mode or
    by a binary file's bytes."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = pathlib.Path(folder.name)
        self.git('init', '-q', '-b', 'main')
        self.commit('base.txt', 'base\n')
        self.base = self.rev('HEAD')
        self.git('switch', '-q', '-c', 'pr')
        self.commit('feature.txt', 'feature\n')
        (self.repo / 'blob.bin').write_bytes(b'\x00\x01\x02')
        self.git('add', 'blob.bin')
        self.git('commit', '-q', '-m', 'binary')
        self.approved = self.rev('HEAD')

    def git(self, *arguments):
        return subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com',
                               *arguments], capture_output=True, text=True, check=True).stdout

    def rev(self, name):
        return self.git('rev-parse', name).strip()

    def commit(self, path, text):
        (self.repo / path).write_text(text)
        self.git('add', path)
        self.git('commit', '-q', '-m', path)

    def rebased(self):
        """main moves on; the PR is rebased onto it."""
        self.git('switch', '-q', 'main')
        self.commit('other.txt', 'other\n')
        self.git('switch', '-q', 'pr')
        self.git('rebase', '-q', 'main')
        return self.rev('HEAD')

    def test_a_rebase_that_only_moves_the_base_keeps_the_fingerprint(self):
        before = gates.own_diff(self.base, self.approved, str(self.repo))
        head = self.rebased()
        self.assertNotEqual(head, self.approved)
        self.assertEqual(gates.own_diff(self.rev('main'), head, str(self.repo)), before)
        # The approved head reads the same against the moved base, since its merge base is still the old one.
        self.assertEqual(gates.own_diff(self.rev('main'), self.approved, str(self.repo)), before)

    def test_paths_that_differ_only_by_a_carriage_return_or_newline_differ(self):
        fingerprints = []
        for name, path in (('cr', 'one\rname'), ('lf', 'one\nname')):
            self.git('switch', '-q', '-c', name, self.base)
            self.commit(path, 'same\n')
            fingerprints.append(gates.own_diff(self.base, self.rev('HEAD'), str(self.repo)))
        self.assertNotEqual(*fingerprints)

    def test_a_submodule_set_to_ignore_changes_still_changes_it(self):
        fingerprints = []
        self.git('config', 'submodule.vendor.ignore', 'all')
        for name, link in (('two', '2' * 40), ('three', '3' * 40)):
            self.git('switch', '-q', '-c', name, self.base)
            (self.repo / '.gitmodules').write_text('[submodule "vendor"]\n\tpath = vendor\n\turl = ./vendor\n\tignore = all\n')
            self.git('add', '.gitmodules')
            self.git('update-index', '--add', '--cacheinfo', f'160000,{link},vendor')
            self.git('commit', '-q', '-m', name)
            fingerprints.append(gates.own_diff(self.base, self.rev('HEAD'), str(self.repo)))
        self.assertNotEqual(*fingerprints)

    def test_same_diff_holds_while_the_base_only_moves_on_and_not_against_another_base(self):
        self.git('switch', '-q', 'main')
        self.commit('other.txt', 'other\n')
        moved = self.rev('HEAD')
        self.git('switch', '-q', 'pr')
        self.assertTrue(gates.same_diff(self.base, moved, self.approved, str(self.repo)))
        # A base that already holds part of the PR, as a retarget can: the PR's own diff is less.
        partway = self.rev('pr~1')
        self.assertFalse(gates.same_diff(self.base, partway, self.approved, str(self.repo)))

    def test_a_mode_or_a_binary_byte_changes_it(self):
        before = gates.own_diff(self.base, self.approved, str(self.repo))
        self.git('update-index', '--chmod=+x', 'feature.txt')
        self.git('commit', '-q', '-m', 'mode')
        moded = self.rev('HEAD')
        self.assertNotEqual(gates.own_diff(self.base, moded, str(self.repo)), before)
        (self.repo / 'blob.bin').write_bytes(b'\x00\x01\x03')
        self.git('commit', '-q', '-am', 'byte')
        self.assertNotEqual(gates.own_diff(self.base, self.rev('HEAD'), str(self.repo)),
                            gates.own_diff(self.base, moded, str(self.repo)))


class Cli(unittest.TestCase):
    def test_decide_tells_an_author_what_an_unattended_reviewer_would_do(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = pathlib.Path(folder.name) / 'GATES.json'
        path.write_text(json.dumps(verdict(decision('D1', 'interface'))))
        script = pathlib.Path(gates.__file__)
        result = subprocess.run([sys.executable, str(script), 'decide', str(path)], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout), (0, 'needs a human: D1\n'))

    def test_check_refuses_a_sensitive_area_the_repo_calls_a_one_way_door_until_it_is_gated(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = pathlib.Path(folder.name) / 'GATES.json'
        sensitive = [{'area': 'money-movement', 'code': 'pay.ts:3'}]
        pr = json.dumps({'body': '', 'headRefOid': HEAD, 'baseRefOid': BASE})
        gh = lambda *arguments, **options: subprocess.CompletedProcess(arguments, 0, stdout=pr)
        listed = ('.github/PULL_REQUEST_TEMPLATE.md:36', 'money movement, and writes to providers')
        with patch.object(gates.subprocess, 'run', gh), patch.object(gates, 'same_diff', lambda *arguments: True), \
                patch.object(gates, 'one_way_doors', lambda base, cwd='.': listed if base == BASE else None), \
                patch('sys.stdout', new_callable=io.StringIO) as printed:
            path.write_text(json.dumps(verdict(decision(None, code='pay.ts:3'), sensitive=sensitive)))
            self.assertEqual(gates.main(['check', '7', str(path)]), 1)
            # Only a one-way-door gate covers it.
            path.write_text(json.dumps(verdict(decision(None, 'pattern', 'pay.ts:3'), sensitive=sensitive)))
            self.assertEqual(gates.main(['check', '7', str(path)]), 1)
            path.write_text(json.dumps(verdict(decision(None, 'one-way-door', 'pay.ts:3'), sensitive=sensitive)))
            self.assertEqual(gates.main(['check', '7', str(path)]), 0)
            # A gated verdict for an older head still fails.
            pr = json.dumps({'body': '', 'headRefOid': BASE, 'baseRefOid': BASE})
            self.assertEqual(gates.main(['check', '7', str(path)]), 1)
        self.assertIn('money-movement at pay.ts:3 is a one-way door by .github/PULL_REQUEST_TEMPLATE.md:36',
                      printed.getvalue())


if __name__ == '__main__':
    unittest.main()

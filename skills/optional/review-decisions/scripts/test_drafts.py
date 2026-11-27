"""drafts.py: the drafts block a --slack reply ends with, which a poster reads and posts as
the reviewer."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import drafts  # noqa: E402

SCRIPT = pathlib.Path(__file__).resolve().parent / 'drafts.py'
HEAD = '0123456789abcdef0123456789abcdef01234567'


def review(**changes):
    data = {'pr': 12, 'head': HEAD, 'summary': 'D2 needs a change; D1 and D3 look right.',
            'comments': [{'path': 'src/totals.ts', 'line': 40, 'side': 'RIGHT', 'start_line': 36,
                          'body': 'D2: keep totals internal until a caller needs them.'},
                         {'path': 'db/schema.sql', 'line': 8, 'side': 'LEFT', 'body': 'Why drop this column?'}],
            'replies': [{'in_reply_to': 2468013579, 'body': 'Agreed, cents it is.'}]}
    data.update(changes)
    return data


def block(data, version=1):
    """A block written by hand, as a reply might hold one, so a malformed one can be read."""
    return f'<!-- review-decisions:drafts v{version} {json.dumps(data)} -->'


class Render(unittest.TestCase):
    def test_a_reply_ends_with_one_block_that_reads_back(self):
        text = 'Press **Post** below to post these.\n\n' + drafts.render(review())
        self.assertTrue(text.splitlines()[-1].startswith('<!-- review-decisions:drafts v1 {"pr": 12, '))
        self.assertTrue(text.endswith('} -->'))
        self.assertEqual(drafts.read(text), review())

    def test_no_comments_and_no_replies_is_an_approval(self):
        approval = review(summary='', comments=[], replies=[])
        self.assertEqual(drafts.read(drafts.render(approval)), approval)

    def test_angle_brackets_are_escaped_so_no_body_closes_the_comment(self):
        tricky = review(summary='a --> b <!-- c', comments=[], replies=[{'in_reply_to': 7, 'body': '<details>x</details> -->'}])
        rendered = drafts.render(tricky)
        inside = rendered[len('<!-- '):-len(' -->')]
        self.assertNotIn('<', inside)
        self.assertNotIn('>', inside)
        self.assertIn('\\u003c', inside)
        self.assertEqual(drafts.read(rendered), tricky)

    def test_invalid_drafts_are_refused_with_each_problem_named(self):
        bad = review(pr='12', head='abc', comments=[{'path': 'a.ts', 'line': 0, 'side': 'UP', 'body': ''}])
        with self.assertRaises(ValueError) as raised:
            drafts.render(bad)
        for named in ('pr is not a PR number', 'head is not a full commit SHA', 'comment 1: line is not a positive number',
                      "comment 1: side is not 'RIGHT' or 'LEFT'", 'comment 1: body is empty'):
            self.assertIn(named, str(raised.exception))


class Read(unittest.TestCase):
    def test_no_block_reads_as_none(self):
        self.assertIsNone(drafts.read('D1 looks right to me.'))
        self.assertIsNone(drafts.read(''))

    def test_the_last_block_wins(self):
        first, second = review(summary='first'), review(summary='second', comments=[], replies=[])
        self.assertEqual(drafts.read(f'{block(first)}\nChanged D2.\n{block(second)}'), second)

    def test_a_last_block_of_another_version_or_malformed_hides_earlier_ones(self):
        self.assertIsNone(drafts.read(f'{block(review())}\n{block(review(), version=2)}'))
        self.assertIsNone(drafts.read(f'{block(review())}\n{block(review(head="abc"))}'))

    def test_a_block_split_over_lines_reads(self):
        self.assertEqual(drafts.read(f'<!-- review-decisions:drafts v1\n{json.dumps(review())}\n-->'), review())

    def test_a_field_added_later_keeps_v1(self):
        self.assertEqual(drafts.read(block(review(event='COMMENT'))), review(event='COMMENT'))

    def test_every_malformed_block_reads_as_none(self):
        comment, reply = review()['comments'][0], review()['replies'][0]
        cases = {
            'not JSON': '<!-- review-decisions:drafts v1 {"pr": 12, -->',
            'not an object': block([review()]),
            'pr a string': block(review(pr='12')),
            'pr a bool': block(review(pr=True)),
            'head short': block(review(head=HEAD[:39])),
            'head not hex': block(review(head='g' * 40)),
            'head upper case': block(review(head=HEAD.upper())),
            'summary not a string': block(review(summary=None)),
            'comments not a list': block(review(comments={})),
            'replies not a list': block(review(replies='none')),
            'comment not an object': block(review(comments=['src/a.ts:3'])),
            'line zero': block(review(comments=[{**comment, 'line': 0}])),
            'line negative': block(review(comments=[{**comment, 'line': -4}])),
            'line a string': block(review(comments=[{**comment, 'line': '40'}])),
            'bad side': block(review(comments=[{**comment, 'side': 'right'}])),
            'start_line on the other side': block(review(comments=[{**comment, 'start_side': 'LEFT'}])),
            'start_line past line': block(review(comments=[{**comment, 'start_line': 41}])),
            'start_line zero': block(review(comments=[{**comment, 'start_line': 0}])),
            'empty path': block(review(comments=[{**comment, 'path': ''}])),
            'empty comment body': block(review(comments=[{**comment, 'body': '  '}])),
            'body not a string': block(review(comments=[{**comment, 'body': ['x']}])),
            'in_reply_to a string': block(review(replies=[{**reply, 'in_reply_to': '2468013579'}])),
            'empty reply body': block(review(replies=[{**reply, 'body': ''}])),
        }
        for field in ('pr', 'head', 'summary', 'comments', 'replies'):
            cases[f'no {field}'] = block({key: value for key, value in review().items() if key != field})
        for field in ('path', 'line', 'side', 'body'):
            cases[f'comment without {field}'] = block(review(comments=[{key: value for key, value in comment.items() if key != field}]))
        for field in ('in_reply_to', 'body'):
            cases[f'reply without {field}'] = block(review(replies=[{key: value for key, value in reply.items() if key != field}]))
        for name, text in cases.items():
            with self.subTest(name):
                self.assertIsNone(drafts.read(text))


class Check(unittest.TestCase):
    def run_check(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = pathlib.Path(folder.name) / 'drafts.json'
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return subprocess.run([sys.executable, str(SCRIPT), 'check', str(path)], capture_output=True, text=True)

    def test_valid_drafts_print_their_block(self):
        result = self.run_check(review())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(drafts.read(result.stdout), review())

    def test_invalid_drafts_fail_naming_the_problem(self):
        result = self.run_check(review(replies=[{'in_reply_to': 0, 'body': 'x'}]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('reply 1: in_reply_to is not a review comment id', result.stderr)

    def test_a_file_that_is_not_json_fails(self):
        result = self.run_check('{"pr": 12,')
        self.assertEqual(result.returncode, 1)
        self.assertIn('not JSON', result.stderr)


if __name__ == '__main__':
    unittest.main()

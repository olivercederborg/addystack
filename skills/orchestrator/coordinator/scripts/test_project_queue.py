"""project_queue.py on project.md lines: the order the user gets items in, ids that never
come back, and the refusals that keep every name a valid turn-block need."""
import unittest
from datetime import datetime

import project_queue as q
import turn_block

NOW = datetime(2026, 11, 18, 14, 5)
BARE = ["# ◆ p", "", "## Goal", "", "Ship it.", "", "## Decisions", "", "- a decision", "", "## Workers", ""]


def project(*items):
    """BARE's lines with a queue holding each (kind, name), added in order."""
    lines = list(BARE)
    q.create(lines)
    for kind, name in items:
        q.add(lines, kind, name, "coordinator", NOW)
    return lines


class Queue(unittest.TestCase):
    def test_a_project_without_the_section_has_no_queue(self):
        self.assertIsNone(q.read(list(BARE)))

    def test_only_create_starts_the_section_before_decisions(self):
        lines = list(BARE)
        with self.assertRaisesRegex(q.QueueError, "no Queue yet: start it with `queue import`"):
            q.add(lines, "do", "pull the laptop's dotfiles", "coordinator", NOW)
        self.assertEqual(lines, BARE)
        lines = project(("do", "pull the laptop's dotfiles"))
        self.assertEqual(lines[:15], [
            "# ◆ p", "", "## Goal", "", "Ship it.", "", "## Queue", "", "Next id: 2", "",
            "| # | Kind | Name | From | Since |", "|---|---|---|---|---|",
            "| 1 | do | pull the laptop's dotfiles | coordinator | 2026-11-18 14:05 |", "", "## Decisions"])

    def test_stuck_runs_come_first_then_calls_then_do_items_oldest_first(self):
        lines = project(("do", "pull the dotfiles"), ("review", "push the cast fix"), ("decide", "keep the v1 export"),
                        ("stuck", "retry R151 or drop it"), ("do", "turn on webhooks"))
        self.assertEqual([(item.id, item.kind) for item in q.read(lines)],
                         [(4, "stuck"), (2, "review"), (3, "decide"), (1, "do"), (5, "do")])

    def test_an_id_never_comes_back(self):
        lines = project(("decide", "keep the v1 export"), ("decide", "request a reviewer on ready"))
        self.assertEqual(q.done(lines, 2).name, "request a reviewer on ready")
        self.assertEqual(q.add(lines, "do", "pull the dotfiles", "coordinator", NOW).id, 3)
        with self.assertRaisesRegex(q.QueueError, "no open Queue item 2"):
            q.done(lines, 2)

    def test_a_row_added_by_hand_past_the_counter_pushes_it_on(self):
        lines = project(("decide", "keep the v1 export"))
        lines.insert(lines.index("| 1 | decide | keep the v1 export | coordinator | 2026-11-18 14:05 |") + 1,
                     "| 7 | do | rotate the token | coordinator | 2026-11-18 |")
        self.assertEqual(q.add(lines, "do", "pull the dotfiles", "coordinator", NOW).id, 8)

    def test_a_pipe_in_a_name_or_source_survives_the_table(self):
        lines = project()
        q.add(lines, "decide", "keep a | b apart", "R153 <t3-thread://v2/e/t> | slot 1", NOW)
        item = q.read(lines)[0]
        self.assertEqual((item.name, item.source), ("keep a | b apart", "R153 <t3-thread://v2/e/t> | slot 1"))

    def test_every_name_it_takes_is_a_valid_need(self):
        for name in ["", "  ", "two\nlines", "x" * 81, "ok", "#12 · 3"]:
            with self.subTest(name=name):
                with self.assertRaises(q.QueueError):
                    q.add(project(), "decide", name, "coordinator", NOW)
        with self.assertRaisesRegex(q.QueueError, "kind 'blocked' isn't one of: stuck, decide, review, do"):
            q.add(project(), "blocked", "keep the export", "coordinator", NOW)
        lines = project(("stuck", "x" * 79 + "y"), ("review", "push it"))
        for item in q.read(lines):
            block = f'<!-- turn {{"state":"stop","needs":[{q.json.dumps(item.need())}],"options":[]}} -->'
            self.assertEqual(turn_block.parse(block).needs[0].kind, "decide" if item.kind == "stuck" else item.kind)

    def test_a_table_it_cant_read_is_an_error_not_an_empty_queue(self):
        for broken in ["| 1 | blocked | keep it | coordinator | 2026-11-18 |", "| x | do | keep it | coordinator | - |",
                       "| 1 | do | keep it | coordinator |"]:
            with self.subTest(row=broken):
                lines = project(("do", "pull the dotfiles"))
                lines.insert(lines.index("## Decisions") - 1, broken)
                with self.assertRaises(q.QueueError):
                    q.read(lines)
        lines = project(("do", "pull the dotfiles"))
        lines[lines.index("| # | Kind | Name | From | Since |")] = "| # | Kind | Name |"
        with self.assertRaisesRegex(q.QueueError, "header"):
            q.read(lines)

    def test_show_prints_the_strip_the_need_and_each_item(self):
        lines = project(("do", "pull the dotfiles"))
        q.add(lines, "decide", "keep the v1 export", "export-v2 <t3-thread://v2/e/8f>", NOW)
        self.assertEqual(q.show(q.read(lines)).split("\n"), [
            "1 of 2 need you · keep the v1 export · export-v2 <t3-thread://v2/e/8f>",
            'needs: [{"id":2,"kind":"decide","name":"keep the v1 export"}]',
            "queue:",
            "  2 decide · keep the v1 export · export-v2 <t3-thread://v2/e/8f> · since 2026-11-18 14:05",
            "  1 do · pull the dotfiles · coordinator · since 2026-11-18 14:05"])
        self.assertTrue(q.show(q.read(project(("do", "pull it")))).startswith("1 of 1 needs you · pull it · coordinator\n"))
        self.assertEqual(q.show(q.read(project())), "Nothing waits on the user.")
        self.assertTrue(q.show(None).startswith("This project has no Queue yet, so what waits on the user is unknown"))

    def test_the_strip_keeps_an_entity_in_a_name_as_typed(self):
        lines = project(("decide", "review &lt;prod&gt; & stage"))
        self.assertEqual(q.strip(q.read(lines)), "1 of 1 needs you · review &amp;lt;prod&amp;gt; & stage · coordinator")

    def test_the_strip_escapes_only_the_html_a_pick_refuses(self):
        lines = project()
        q.add(lines, "decide", "keep <pre> and <!-- x --> out if A < B", "R153 <t3-thread://v2/e/t> <details>", NOW)
        self.assertEqual(q.strip(q.read(lines)), "1 of 1 needs you · keep &lt;pre> and &lt;!-- x --> out if A < B · "
                                                 "R153 <t3-thread://v2/e/t> &lt;details>")

    def test_a_need_it_prints_parses_whatever_the_name_holds(self):
        for name in ["discuss A --> B", "keep <!-- this --> out", "merge #12 if a > b"]:
            with self.subTest(name=name):
                printed = q.show(q.read(project(("decide", name)))).split("\n")[1]
                self.assertTrue(printed.startswith("needs: ["))
                block = f'<!-- turn {{"state":"stop","needs":{printed[len("needs: "):]},"options":[]}} -->'
                self.assertEqual(turn_block.parse(block).needs[0].name, name)


class Batch(unittest.TestCase):
    """Calls of one batch waiting at the same moment go on one card, so one go answers them."""

    def test_the_first_batched_add_writes_the_column_and_keeps_every_row(self):
        lines = project(("decide", "keep the v1 export"))
        q.add(lines, "review", "post the reply to Ana on #41", "rv41", NOW, batch="post")
        at = lines.index("| # | Kind | Name | From | Since | Batch |")
        self.assertEqual(lines[at:at + 4], [
            "| # | Kind | Name | From | Since | Batch |", "|---|---|---|---|---|---|",
            "| 1 | decide | keep the v1 export | coordinator | 2026-11-18 14:05 |  |",
            "| 2 | review | post the reply to Ana on #41 | rv41 | 2026-11-18 14:05 | post |"])
        self.assertEqual([(item.id, item.batch) for item in q.read(lines)], [(1, ""), (2, "post")])
        self.assertEqual(q.done(lines, 1).name, "keep the v1 export")

    def test_the_top_item_shares_its_card_with_its_batch_alone(self):
        lines = project(("decide", "keep the v1 export"))
        for name, batch in [("post the reply to Ana on #41", "post"), ("merge #12 and #13", "merge:receipts"),
                            ("re-request Ana on #42", "post"), ("approve #43 with two comments", "post")]:
            q.add(lines, "review", name, "rv", NOW, batch=batch)
        self.assertTrue(q.show(q.read(lines)).startswith("1 of 5 need you · keep the v1 export · coordinator\n"),
                        "an unbatched top item shows alone")
        q.done(lines, 1)
        shown = q.show(q.read(lines)).splitlines()
        self.assertEqual(shown[0], "3 of 4 need you, on one card · post · 2 post the reply to Ana on #41; "
                                   "4 re-request Ana on #42; 5 approve #43 with two comments")
        self.assertEqual(turn_block.parse('<!-- turn {"state":"stop","' + shown[1].replace(": ", '":', 1) + ',"options":[]} -->')
                         .needs, (turn_block.Need(2, "review", "post the reply to Ana on #41"),
                                  turn_block.Need(4, "review", "re-request Ana on #42"),
                                  turn_block.Need(5, "review", "approve #43 with two comments")))
        for ident in (2, 4, 5):
            q.done(lines, ident)
        self.assertTrue(q.show(q.read(lines)).startswith("1 of 1 needs you · merge #12 and #13 · rv\n"),
                        "a batch of one is a card of one")

    def test_a_card_stays_in_its_priority_band(self):
        # Codex review of r204/batch, round 1: a card took a batch item the priority puts last.
        lines = project()
        q.add(lines, "review", "priority: post to Ana on #41", "rv41", NOW, batch="post")
        q.add(lines, "decide", "priority: settle the export", "w", NOW)
        q.add(lines, "review", "post to Bo on #42", "rv42", NOW, batch="post")
        q.add(lines, "review", "priority: post to Ana on #43", "rv43", NOW, batch="post")
        ranked = q.read(lines, lambda item: item.name.startswith("priority"), NOW)
        self.assertEqual([item.id for item in q.card(ranked)], [1, 4], "Bo's post waits behind the priority's decide")
        self.assertEqual([item.id for item in q.card(q.read(lines))], [1, 3, 4], "with no priority, one band")

    def test_open_items_join_a_batch_and_keep_their_ids(self):
        lines = project(("review", "post to Ana on #41"), ("decide", "keep the v1 export"), ("review", "post to Ana on #42"))
        self.assertEqual([item.id for item in q.batch(lines, "post", [1, 3])], [1, 3])
        self.assertTrue(q.show(q.read(lines)).startswith("2 of 3 need you, on one card · post · 1 post to Ana on #41; "
                                                         "3 post to Ana on #42\n"))
        with self.assertRaisesRegex(q.QueueError, "no open Queue item 9"):
            q.batch(lines, "post", [9])

    def test_a_queue_section_with_no_table_says_how_to_fix_it(self):
        with self.assertRaisesRegex(q.QueueError, "the Queue table's header isn't"):
            q.read(["## Queue", "", "Next id: 1", ""])

    def test_batch_leaves_a_table_it_cant_read_as_it_is(self):
        # Codex review of r204/batch, round 2: it rewrote a header with From and Since swapped.
        swapped = ["## Queue", "", "Next id: 2", "", "| # | Kind | Name | Since | From |", "|---|---|---|---|---|",
                   "| 1 | review | post Ana | 2026-11-18 14:05 | rv41 |", ""]
        for lines in (list(swapped), ["## Queue", "", "Next id: 1", ""]):
            before = list(lines)
            with self.assertRaisesRegex(q.QueueError, "the Queue table's header isn't"):
                q.batch(lines, "post", [1])
            self.assertEqual(lines, before)
        # Codex review of r204/batch, round 3: a bad row raised after the header was rewritten.
        bad_row = ["## Queue", "", "Next id: 2", "", "| # | Kind | Name | From | Since |", "|---|---|---|---|---|",
                   "| 1 | blocked | post Ana | rv | 2026-11-18 14:05 |", ""]
        for change in (lambda lines: q.batch(lines, "post", [1]),
                       lambda lines: q.add(lines, "review", "post Bo", "rv", NOW, batch="post")):
            lines = list(bad_row)
            with self.assertRaisesRegex(q.QueueError, "a Queue row it can't read"):
                change(lines)
            self.assertEqual(lines, bad_row)

    def test_a_batch_is_one_word(self):
        lines = project()
        for batch in ["post replies", "x" * 41, "post|merge"]:
            with self.assertRaisesRegex(q.QueueError, "--batch takes one word"):
                q.add(lines, "review", "post the reply", "rv", NOW, batch=batch)
        self.assertNotIn("Batch", " ".join(lines))


if __name__ == "__main__":
    unittest.main()

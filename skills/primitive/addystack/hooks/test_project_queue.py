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
            q.add(lines, "do", "pull the Mac's dotfiles", "coordinator", NOW)
        self.assertEqual(lines, BARE)
        lines = project(("do", "pull the Mac's dotfiles"))
        self.assertEqual(lines[:15], [
            "# ◆ p", "", "## Goal", "", "Ship it.", "", "## Queue", "", "Next id: 2", "",
            "| # | Kind | Name | From | Since |", "|---|---|---|---|---|",
            "| 1 | do | pull the Mac's dotfiles | coordinator | 2026-11-18 14:05 |", "", "## Decisions"])

    def test_stuck_runs_come_first_then_calls_then_do_items_oldest_first(self):
        lines = project(("do", "pull the dotfiles"), ("review", "push the cast fix"), ("decide", "keep the v1 export"),
                        ("stuck", "retry R151 or drop it"), ("do", "turn on webhooks"))
        self.assertEqual([(item.id, item.kind) for item in q.read(lines)],
                         [(4, "stuck"), (2, "review"), (3, "decide"), (1, "do"), (5, "do")])

    def test_an_id_never_comes_back(self):
        lines = project(("decide", "keep the v1 export"), ("decide", "request Casper on ready"))
        self.assertEqual(q.done(lines, 2).name, "request Casper on ready")
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
        self.assertEqual(q.show(None), "Nothing waits on the user.")

    def test_the_strip_writes_brackets_as_entities_and_keeps_links(self):
        lines = project()
        q.add(lines, "decide", "merge #123 if A < B & C", "R153 <t3-thread://v2/e/t> <slot 1>", NOW)
        self.assertEqual(q.strip(q.read(lines)),
                         "1 of 1 needs you · merge #123 if A &lt; B &amp; C · R153 <t3-thread://v2/e/t> &lt;slot 1&gt;")

    def test_a_need_it_prints_parses_whatever_the_name_holds(self):
        for name in ["discuss A --> B", "keep <!-- this --> out", "merge #12 if a > b"]:
            with self.subTest(name=name):
                printed = q.show(q.read(project(("decide", name)))).split("\n")[1]
                self.assertTrue(printed.startswith("needs: ["))
                block = f'<!-- turn {{"state":"stop","needs":{printed[len("needs: "):]},"options":[]}} -->'
                self.assertEqual(turn_block.parse(block).needs[0].name, name)

    def test_the_strip_matches_what_show_prints(self):
        for count in (1, 3, 12):
            items = q.read(project(*[("do", f"step number {n}") for n in range(count)]))
            self.assertEqual(q.STRIP.search(q.strip(items)).group(2), str(count))
        self.assertIsNone(q.STRIP.search("21 of 3 needed"))


if __name__ == "__main__":
    unittest.main()

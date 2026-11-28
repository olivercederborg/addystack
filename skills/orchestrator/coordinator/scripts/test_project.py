"""project.py on a project.md shaped like a real coordinator's: blank lines between some
decisions, a Result section, notes under the Workers table, and a learning that runs
into the Listening heading. Each edit changes only its own lines.
Run: python3 -m unittest discover -s coordinator/scripts"""
import pathlib, re, subprocess, sys, tempfile, unittest
from datetime import date, datetime, timedelta

SCRIPT = pathlib.Path(__file__).resolve().parent / "project.py"
TODAY = date.today().isoformat()

PROJECT = """# ◆ audit

Coordinator: <t3-thread://v2/e/c> · Checkout: ~/skills · Mode: personal, planning autonomous

## Goal

Audit the suite.
Plan: ~/plan.md
Proof: five reports.
Follow-ups: none

## Result (interim, 2026-10-30)

Shipped: #149.

## Decisions

- 2026-10-29 · coordinator: pilot is teammate-reviews.

- 2026-10-30 · the user: "a" to "merge #202" → merged 31ddd00.

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|
| review (pilot) | <t3-thread://v2/e/r> · task t1 | — | done | — | report written |
| review-quality | <t3-thread://v2/e/q> · task t2 | — | running (slot 1) | — | launched |

Proofs:
- review: a ranked report.

## Learnings

- 2026-10-29 · review: comment substance is good.
Follow-ups from r3: delete the transition hooks.
## Listening

- Heartbeat: scheduled-task:hb
- Reminder: scheduled-task:ci (20:00, one-time)
- Watches: none
"""


class Fixture:
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.dir)])
        (self.dir / "project.md").write_text(PROJECT)

    def project(self, *args, code=0, stdin=None):
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.dir), *args], capture_output=True, text=True,
                                input=stdin)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def text(self):
        return (self.dir / "project.md").read_text()


class Project(Fixture, unittest.TestCase):
    def test_a_decision_goes_after_the_last_one(self):
        self.project("decide", "R5 asked: may a verifier record without a checkout? → a · source: the user: \"a\"")
        self.assertEqual(self.text(), PROJECT.replace(
            "merged 31ddd00.\n", f"merged 31ddd00.\n- {TODAY} · R5 asked: may a verifier record without a checkout?"
                                 " → a · source: the user: \"a\"\n"))

    def test_a_learning_from_stdin_keeps_a_blank_line_before_listening(self):
        self.project("learn", "-", stdin="r5: `a | b` names verify-work/SKILL.md\nand wraps\n")
        self.assertEqual(self.text(), PROJECT.replace(
            "transition hooks.\n## Listening",
            f"transition hooks.\n- {TODAY} · r5: `a | b` names verify-work/SKILL.md\n  and wraps\n\n## Listening"))

    def test_a_worker_row_changes_only_the_named_columns(self):
        self.project("worker", "review-quality", "--state", "done: #12 MERGED", "--last", "merged a1b2c3d, 15:40")
        self.assertEqual(self.text(), PROJECT.replace(
            "| running (slot 1) | — | launched |", "| done: #12 MERGED | — | merged a1b2c3d, 15:40 |"))
        self.project("worker", "review", "--waits", "the user's go | merge")  # matches `review (pilot)`
        self.assertIn("| review (pilot) | <t3-thread://v2/e/r> · task t1 | — | done | the user's go \\| merge |", self.text())

    def test_a_new_row_without_a_state_is_refused_as_a_likely_typo(self):
        result = self.project("worker", "review-qualty", "--last", "pushed abc", code=1)
        self.assertEqual(result.stderr, "no Workers row matches 'review-qualty': a new row needs --state\n")
        self.assertEqual(self.text(), PROJECT)

    def test_an_edit_keeps_the_files_mode(self):
        (self.dir / "project.md").chmod(0o644)
        self.project("decide", "x")
        self.assertEqual((self.dir / "project.md").stat().st_mode & 0o777, 0o644)

    def test_a_new_worker_row_goes_under_the_table(self):
        self.project("worker", "r5", "--thread", "<t3-thread://v2/e/5> · task t5", "--state", "queued",
                     "--waits", "slot")
        self.assertIn("| launched |\n| r5 | <t3-thread://v2/e/5> · task t5 | — | queued | slot | — |\n\nProofs:",
                      self.text())

    def test_a_state_outside_the_vocabulary_is_refused(self):
        for state in ["blocked", "in progress", "doneish", "replaced by"]:
            with self.subTest(state=state):
                result = self.project("worker", "review", "--state", state, code=1)
                self.assertIn("doesn't start with one of: queued, overdue", result.stderr)
        self.assertEqual(self.text(), PROJECT)
        for state in ["replaced by r5", "waiting (no slot), retry 1", "absorbed into r4"]:
            self.project("worker", "review", "--state", state)

    def test_a_row_short_of_a_cell_is_refused(self):
        short = PROJECT.replace("| running (slot 1) | — | launched |", "| running (slot 1) | launched |")
        (self.dir / "project.md").write_text(short)
        result = self.project("worker", "review-quality", "--last", "pushed abc", code=1)
        self.assertEqual(result.stderr, "the 'review-quality' row has 5 cells and the header 6: fix it by hand\n")
        self.assertEqual(self.text(), short)

    def test_listen_replaces_its_line_or_adds_one(self):
        self.project("listen", "Watches", "#1 (owner a)\n#2 (owner b)", code=1)
        self.project("listen", "Heartbeat", "none")
        self.project("listen", "Startup", "scheduled-task:st")
        self.assertEqual(self.text(), PROJECT.replace("- Heartbeat: scheduled-task:hb", "- Heartbeat: none")
                         .replace("- Watches: none\n", "- Watches: none\n- Startup: scheduled-task:st\n"))

    def test_init_writes_a_skeleton_the_edits_work_on(self):
        init = ["init", "--project", "p", "--coordinator", "<t3-thread://v2/e/c>", "--checkout", "~/p",
                "--mode", "personal, planning autonomous", "--goal", "Ship it.", "--proof", "a merged PR"]
        self.project(*init, code=1)  # it never overwrites
        self.assertEqual(self.text(), PROJECT)
        (self.dir / "project.md").unlink()
        self.project(*init)
        self.project("decide", "first")
        self.project("learn", "first")
        self.project("worker", "a", "--state", "running")
        text = self.text()
        self.assertTrue(text.startswith("# ◆ p\n\nCoordinator: <t3-thread://v2/e/c> · Checkout: ~/p · Mode: personal,"))
        self.assertIn(f"## Decisions\n\n- {TODAY} · first\n\n## Workers", text)
        self.assertIn("|---|---|---|---|---|---|\n| a | — | — | running | — | — |\n\n## Learnings", text)
        self.assertIn(f"## Learnings\n\n- {TODAY} · first\n\n## Listening\n\n- Heartbeat: none\n", text)
        self.assertIn("Follow-ups: none\n\n## Queue\n\nNext id: 1\n\n| # | Kind | Name | From | Since |\n"
                      "|---|---|---|---|---|\n\n## Decisions", text)
        self.assertEqual(self.project("queue", "show").stdout, "Nothing waits on the user.\n")


class Queue(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.project("queue", "import", stdin='<!-- turn {"state":"done"} -->')  # PROJECT predates the queue

    def test_a_project_from_before_the_queue_starts_it_by_import(self):
        (self.dir / "project.md").write_text(PROJECT)
        self.assertIn("no Queue yet: start it with `queue import`",
                      self.project("queue", "add", "decide", "keep the v1 export", code=1).stderr)
        reply = ('⏳ **R153 runs.**\n\n<!-- turn {"state":"running","elapsed":"1 min","needs":[{"id":63,"kind":"do",'
                 '"name":"pull the dotfiles"}],"standing":[{"id":64,"kind":"decide","name":"request a reviewer on ready"},'
                 '{"id":5,"kind":"decide","name":"merge #39"}]} -->')
        out = self.project("queue", "import", stdin=reply).stdout
        self.assertTrue(out.startswith("imported 1: decide · merge #39\nimported 2: do · pull the dotfiles\n"
                                       "imported 3: decide · request a reviewer on ready\n1 of 3 need you · merge #39 · "), out)
        self.assertIn("the Queue exists", self.project("queue", "import", stdin=reply, code=1).stderr)
        (self.dir / "project.md").write_text(PROJECT)
        duplicate = '{"state":"done","standing":[{"id":5,"kind":"do","name":"pull it"},{"id":5,"kind":"do","name":"push it"}]}'
        for refused in ["no block", duplicate]:
            self.assertIn("takes a turn block", self.project("queue", "import", stdin=refused, code=1).stderr)
        self.assertEqual(self.text(), PROJECT)
        (self.dir / "project.md").write_text(PROJECT)
        wrapped = ('{"state":"done","standing":[{"id":4,"kind":"decide","name":"approve \\nthe release"},'
                   '{"id":5,"kind":"decide","name":"keep token `a  b`"}]}')
        out = self.project("queue", "import", stdin=wrapped).stdout
        self.assertIn("imported 1: decide · approve the release\nimported 2: decide · keep token `a  b`\n", out)
        (self.dir / "project.md").write_text(PROJECT)
        quoted = 'A block looks like `<!-- turn {"state":"done"} -->`.\n\n' + reply
        self.assertIn("imported 3: decide · request a reviewer on ready", self.project("queue", "import", stdin=quoted).stdout)
        # Who asked and a stuck run, which the turn block can't say, come from the coordinator.
        (self.dir / "project.md").write_text(PROJECT)
        out = self.project("queue", "import", "--from", "64=R153 <t3-thread://v2/e/t>", "--stuck", "5", stdin=reply).stdout
        self.assertIn("imported 1: stuck · merge #39", out)
        self.assertIn("1 of 3 need you · merge #39 · coordinator", out)
        self.assertIn("  3 decide · request a reviewer on ready · R153 <t3-thread://v2/e/t> · since", out)
        for wrong, error in [(["--stuck", "9"], "the turn block has no item 9"), (["--from", "64"], "--from takes ID=WHO")]:
            (self.dir / "project.md").write_text(PROJECT)
            self.assertIn(error, self.project("queue", "import", *wrong, stdin=reply, code=1).stderr)
            self.assertEqual(self.text(), PROJECT)

    def test_add_done_and_show_keep_the_queue_and_its_answers(self):
        added = self.project("queue", "add", "do", "pull the laptop's dotfiles").stdout
        self.assertTrue(added.startswith("queued 1: do · pull the laptop's dotfiles\n1 of 1 needs you · pull the laptop's dotfiles · coordinator\n"))
        self.project("queue", "add", "decide", "keep the v1 export", "--from", "export-v2 <t3-thread://v2/e/8f>")
        self.assertEqual(self.project("queue", "show").stdout.split("\n")[:2], [
            "1 of 2 need you · keep the v1 export · export-v2 <t3-thread://v2/e/8f>",
            'needs: [{"id":2,"kind":"decide","name":"keep the v1 export"}]'])
        self.assertIn("## Queue\n\nNext id: 3\n\n| # | Kind | Name | From | Since |\n|---|---|---|---|---|\n"
                      "| 1 | do | pull the laptop's dotfiles | coordinator |", self.text())
        self.assertTrue(self.text().index("## Queue") < self.text().index("## Decisions"))
        done = self.project("queue", "done", "2", "--answer", "-", stdin='keep it one release · the user: "a"\n').stdout
        self.assertTrue(done.startswith("done 2: decide · keep the v1 export\n1 of 1 needs you · pull the laptop's dotfiles · coordinator\n"))
        self.assertIn(f"merged 31ddd00.\n- {TODAY} · export-v2 <t3-thread://v2/e/8f> asked: keep the v1 export (queue 2, "
                      "decide) → keep it one release · the user: \"a\"\n", self.text())
        self.project("queue", "done", "1", "--answer", "pulled · the user: \"done.\nBoth machines.\"")
        self.assertIn(f"- {TODAY} · coordinator asked: pull the laptop's dotfiles (queue 1, do) → pulled · the user: "
                      "\"done.\n  Both machines.\"\n", self.text())

    def test_an_answer_with_any_line_ending_stays_inside_its_decision(self):
        self.project("queue", "add", "decide", "keep the v1 export")
        self.project("queue", "done", "1", "--answer", "yes\r## Workers\r\nno table")
        self.assertIn(f"- {TODAY} · coordinator asked: keep the v1 export (queue 1, decide) → yes\n  ## Workers\n  no table",
                      self.text())
        self.assertEqual(self.text().count("\n## Workers"), 1)
        self.project("worker", "review", "--last", "pushed abc")

    def test_a_refused_queue_edit_leaves_the_file_untouched(self):
        self.project("queue", "add", "decide", "keep the v1 export")
        before = self.text()
        for args, error in [(["add", "decide", "ok"], "a word of 3+ letters"),
                            (["done", "7", "--answer", "a"], "no open Queue item 7"),
                            (["done", "1", "--answer", "  "], "--answer takes the answer")]:
            with self.subTest(args=args):
                self.assertIn(error, self.project("queue", *args, code=1).stderr)
                self.assertEqual(self.text(), before)
        self.project("queue", "add", "blocked", "keep it", code=2)

    def test_a_phase_keeps_the_open_queue(self):
        self.project("queue", "add", "decide", "keep the v1 export")
        queue = self.text()[self.text().index("## Queue"):self.text().index("## Decisions")]
        self.project("phase", "audit", "--result", "five reports", *NEXT)
        self.assertIn(queue, self.text())


class PriorityLine(unittest.TestCase):
    """The user's priority, said in one project, orders every project's queue on the machine."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        self.heard, self.other = self.root / "audit", self.root / "export"
        for folder in (self.heard, self.other):
            folder.mkdir()
            (folder / "project.md").write_text(PROJECT.replace("| running (slot 1) | — | launched |",
                                                               "| running (slot 1) | — | launched |\n"
                                                               "| docs | — | — | queued | Ana's fix | — |\n"
                                                               "| ana-fixes | — | #41 by ana | queued | slot | — |"))
            self.run_in(folder, "queue", "import", stdin='<!-- turn {"state":"done"} -->')
        for kind, name, source in [("decide", "keep the v1 export", "export-v2"),
                                   ("review", "post the reply to Ana on #41", "rv41"),
                                   ("review", "approve #410 for Ben", "rv410")]:
            self.run_in(self.other, "queue", "add", kind, name, "--from", source)

    def run_in(self, folder, *args, code=0, stdin=None):
        result = subprocess.run([sys.executable, str(SCRIPT), str(folder), *args], capture_output=True, text=True,
                                input=stdin)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def order(self):
        return [line.split()[0] for line in self.run_in(self.other, "queue", "show").stdout.splitlines()
                if line.startswith("  ")]

    def test_one_project_hears_it_and_another_reorders_with_no_message(self):
        self.assertEqual(self.order(), ["1", "2", "3"])
        said = self.run_in(self.heard, "priority", "set", "specifically Ana's PRs are the most important right now",
                           "--match", "Ana", "--match", "#41").stdout
        self.assertRegex(said, r'^- \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{6} · audit · until .* · match: Ana, #41 · "specifically')
        out = self.run_in(self.other, "queue", "show").stdout
        self.assertEqual(self.order(), ["2", "1", "3"], "#410 and Ben's name aren't Ana's #41")
        self.assertTrue(out.startswith("1 of 3 need you · post the reply to Ana on #41 · rv41\n"
                                       'needs: [{"id":2,"kind":"review","name":"post the reply to Ana on #41"}]'), out)
        self.assertIn("first here: 2 post the reply to Ana on #41; units ana-fixes\nNew here: echo it in one line", out)
        stamp = said.split(" · ")[0][2:]
        self.run_in(self.other, "listen", "Priority", stamp)
        out = self.run_in(self.other, "queue", "show").stdout
        self.assertNotIn("New here", out, "the coordinator echoes it once")
        self.assertIn('"specifically Ana\'s PRs are the most important right now" · first here: 2 post', out)
        self.assertIn("first here: units ana-fixes\nNew here", self.run_in(self.heard, "queue", "show").stdout)
        self.run_in(self.heard, "priority", "clear")
        self.assertEqual((self.order(), self.run_in(self.other, "priority", "show").stdout), (["1", "2", "3"],
                                                                                               "no priority holds\n"))

    def test_an_item_waiting_a_day_under_it_goes_first_so_none_starves(self):
        text = (self.other / "project.md").read_text()
        text = re.sub(r"(\| post the reply to Ana on #41 \| \S+ \| )[^|]+", r"\g<1>2020-01-01 09:00 ", text)
        (self.other / "project.md").write_text(text)
        self.run_in(self.heard, "priority", "set", "Ben first", "--match", "Ben")
        self.assertEqual(self.order(), ["3", "1", "2"], "an old item ages only from when the priority was said")
        line = (self.root / "priority.md").read_text()
        said = re.search(r"- (\S+ \S+) · ", line)[1]
        (self.root / "priority.md").write_text(line.replace(f"- {said} · ", "- 2026-01-01 09:00 · ").replace(
            re.search(r"until (\S+ \S+)", line)[1], "2999-01-01 00:00"))
        text = re.sub(r"(\| keep the v1 export \| \S+ \| )[^|]+", r"\g<1>2999-01-01 09:00 ", text)
        (self.other / "project.md").write_text(text)
        self.assertEqual(self.order(), ["2", "3", "1"], "what waited a day under it, then the priority's, then the rest")
        self.run_in(self.heard, "priority", "set", "nothing here", "--match", "zebra")
        self.assertIn("names nothing here", self.run_in(self.other, "queue", "show").stdout)
        self.assertEqual(self.order(), ["1", "2", "3"], "a priority that names nothing here leaves the order as before")

    def test_it_reads_pr_ranges_and_urls_keeps_the_words_and_echoes_each_line(self):
        # Codex review of r204/priority, round 1.
        self.run_in(self.other, "queue", "add", "decide", "mark #6242–#6244 ready", "--from", "w")
        self.run_in(self.other, "queue", "add", "review", "post on https://github.com/o/r/pull/7001", "--from", "w")
        said = self.run_in(self.heard, "priority", "set", 'only the "urgent" PRs', "--match", "#6243", "#7001").stdout
        self.assertIn('match: #6243, #7001 · "only the "urgent" PRs"', said)
        self.assertEqual(self.order()[:2], ["4", "5"], "a range and a URL name their PRs")
        self.assertIn('"only the "urgent" PRs"', self.run_in(self.other, "priority", "show").stdout)
        first = said.split(" · ")[0][2:]
        self.run_in(self.other, "listen", "Priority", first)
        (self.root / "priority.md").write_text((self.root / "priority.md").read_text().replace(first, "2026-01-01 09:00:00"))
        self.assertIn("New here", self.run_in(self.other, "queue", "show").stdout,
                      "a second line set in the same minute is echoed too")

    def test_round_two_edges_of_matching_echo_and_aging(self):
        # Codex review of r204/priority, round 2, read in-process.
        sys.path.insert(0, str(SCRIPT.parent))
        import project as p, project_queue as q
        line = lambda term, said="2026-01-01 09:00:00": p.Priority(said, "audit", "2999-01-01 00:00", (term,), "w")
        for term, text in [("#6242–#6244", "Review #6242–#6244"), ("#6242–#6244", "Review #6243"),
                           ("https://github.com/o/r/pull/7001", "Review o/r#7001"), ("#7001", "post on o/r#7001")]:
            self.assertTrue(line(term).matches(text), (term, text))
        self.assertFalse(line("#62").matches("Review #6243"))
        root = self.root / "same-second"
        root.mkdir()
        now = datetime(2026, 11, 28, 12, 0, 59)
        first = p.set_priority(root, "Ana first", ["Ana"], "audit", "2999-01-01", now)
        second = p.set_priority(root, "Ana now", ["Ana"], "audit", "2999-01-01", now.replace(microsecond=5))
        self.assertNotEqual(first.said, second.said)
        lines = p.SKELETON.format(project="p", coordinator="c", checkout="x", mode="m", goal="g", proof="p").split("\n")
        q.add(lines, "review", "Review old release", "w", now - timedelta(days=3))
        q.add(lines, "do", "Old task", "w", now - timedelta(days=7))
        q.add(lines, "review", "Review Ana PR", "w", now)
        p.worker(lines, "ana-docs", state="queued", waits="pilot proof")
        held = line("Ana", (now - timedelta(days=2)).strftime(p.SAID))
        ranked = q.read(lines, p._ahead(held, lines), now, held_since=p._said(held))
        self.assertEqual([item.name for item in ranked], ["Old task", "Review old release", "Review Ana PR"])
        self.assertIn("first here: 2 Old task (waited a day under it), 1 Review old release (waited a day under it), "
                      "3 Review Ana PR; units ana-docs (waits on pilot proof)", p.priority_note(lines, held))
        # Round 3: a PR term keeps its repo, a phrase stays a phrase, a long range is an interval.
        for term, text, hit in [("acme/beta#41", "Merge acme/alpha#41", False), ("acme/beta#41", "Merge acme/beta#41", True),
                                ("beta#41", "https://github.com/acme/beta/pull/41", True),
                                ("review #41", "merge #41", False), ("review #41", "review #41 now", True),
                                ("#5602", "Review #5581–#5618 together", True),
                                ("#5581–#5618", "post on #5602", True), ("#41", "Merge acme/alpha#41", True),
                                # Blast radius of #154 (R206, risk 6): a term's owner counts too.
                                ("alice/api#41", "Merge bob/api#41", False), ("alice/api#41", "Merge alice/api#41", True),
                                ("alice/api#41", "https://github.com/bob/api/pull/41", False),
                                ("https://github.com/alice/api/pull/41", "Merge alice/api#41", True),
                                ("api#41", "Merge bob/api#41", True)]:
            self.assertEqual(line(term).matches(text), hit, (term, text))

    def test_it_ends_at_its_time_and_refuses_what_it_cant_hold(self):
        self.run_in(self.heard, "priority", "set", "Ana first", "--match", "Ana", "--until", "2999-01-01")
        self.assertIn("until 2999-01-01 00:00", self.run_in(self.other, "priority", "show").stdout)
        line = (self.root / "priority.md").read_text().replace("until 2999-01-01", "until 2020-01-01")
        (self.root / "priority.md").write_text(line)
        self.assertEqual(self.order(), ["1", "2", "3"], "an expired priority orders nothing")
        for args, error in [(["--match", "Ana", "--until", "2020-01-01"], "already past"),
                            (["--match", "Ana, Ben"], "without a comma"),
                            (["--match", "Ana", "--until", "friday"], "--until takes")]:
            self.assertIn(error, self.run_in(self.heard, "priority", "set", "Ana first", *args, code=1).stderr)
        self.run_in(self.heard, "priority", "set", "Ana first", code=2)
        (self.root / "priority.md").write_text("# Priority\n\n- garbled\n")
        shown = self.run_in(self.other, "queue", "show")
        self.assertEqual((self.order(), "no one priority line" in shown.stderr), (["1", "2", "3"], True))

    def test_a_file_it_cant_read_warns_and_the_queue_goes_on(self):
        # Blast radius of #154 (R206, risk 2): each of these stopped `queue show` for every coordinator.
        good = '- 2026-11-28 01:00:00.000000 · audit · until {until} · match: Ana · "Ana first"\n'
        path = self.root / "priority.md"
        for name, write in [("an impossible until", lambda: path.write_text(good.format(until="2026-13-45 99:99"))),
                            ("an impossible said", lambda: path.write_text(
                                good.replace("2026-11-28 01:00", "2026-02-30 01:00").format(until="2999-01-01 00:00"))),
                            ("invalid UTF-8", lambda: path.write_bytes(b"- \xff\xfe\n")),
                            ("a directory", path.mkdir)]:
            with self.subTest(name):
                write()
                shown = self.run_in(self.other, "queue", "show")
                self.assertEqual(self.order(), ["1", "2", "3"])
                self.assertIn(str(path), shown.stderr)
                path.rmdir() if path.is_dir() else path.unlink()


LISTENING = PROJECT[PROJECT.index("## Listening"):]
NEXT = ["--goal", "Fix what the audit found.", "--proof", "each finding merged"]


class Phase(Fixture, unittest.TestCase):
    def files(self):
        return sorted(p.name for p in self.dir.rglob("*") if p.is_file())

    def test_a_phase_archives_the_file_and_resets_only_the_phase(self):
        result = self.project("phase", "audit", "--result", "five reports", *NEXT)
        self.assertEqual(result.stdout, f"{self.dir}/phases/01-audit.md\n{self.dir}/project.md\n")
        self.assertEqual((self.dir / "phases/01-audit.md").read_bytes(), PROJECT.encode())
        self.assertEqual(self.text(), PROJECT[:PROJECT.index("## Goal")] + f"""## Goal

Fix what the audit found.
Proof: each finding merged
Follow-ups: none

## Phases

- {TODAY} · 01-audit: five reports · phases/01-audit.md

## Decisions

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|
| review-quality | <t3-thread://v2/e/q> · task t2 | — | running (slot 1) | — | launched |

Proofs:
- review: a ranked report.

## Learnings

""" + LISTENING)

    def test_a_parked_project_starts_again_and_numbers_the_next_archive(self):
        self.project("start", *NEXT, code=1)  # its phase is running
        self.project("phase", "audit", "--result", "five reports", "--park", "until the user asks")
        parked = self.text()
        self.assertIn(f"## Goal\n\nParked {TODAY}: until the user asks\nFollow-ups: none\n\n## Phases\n", parked)
        self.assertEqual(self.project("phase", "fixes", "--result", "r", *NEXT, code=1).stderr,
                         "the project is parked: start its next phase with start\n")
        self.assertEqual((self.text(), self.files()), (parked, ["01-audit.md", "project.md"]))
        self.project("start", *NEXT)
        self.assertIn("## Goal\n\nFix what the audit found.\nProof: each finding merged\nFollow-ups: none\n\n",
                      self.text())
        started = self.text().encode()
        self.project("phase", "fixes", "--result", "all merged", "--park", "done for now")
        self.assertEqual((self.dir / "phases/02-fixes.md").read_bytes(), started)
        self.assertIn(f"## Phases\n\n- {TODAY} · 01-audit: five reports · phases/01-audit.md\n"
                      f"- {TODAY} · 02-fixes: all merged · phases/02-fixes.md\n\n## Decisions", self.text())

    def test_a_retry_after_a_failed_write_reuses_its_archive(self):
        self.project("phase", "audit", "--result", "five reports", *NEXT)
        (self.dir / "project.md").write_text(PROJECT)  # as if the project.md write had failed
        self.project("phase", "audit", "--result", "five reports", *NEXT)
        self.assertEqual(self.files(), ["01-audit.md", "project.md"])
        self.assertIn("· 01-audit: five reports · phases/01-audit.md\n\n## Decisions", self.text())

    def test_follow_ups_unknown_sections_and_unreadable_rows_carry(self):
        real = (PROJECT.replace("Follow-ups: none\n", "Follow-ups:\n- lockfile risk\n  wraps here\n\n- stray rows\n"
                                "* starred\n1. numbered\nunindented tail\n\n"
                                "### Milestones done\n\n- G1–G6\n")
                .replace("| done | — | report written |", "| done | report written |")
                .replace("## Learnings", "## Queue (cards for the user)\n\n- c1\n\n## Learnings"))
        (self.dir / "project.md").write_text(real)
        ended = self.project("phase", "audit", "--result", "five reports", "--park", "p")
        self.assertIn("kept 1 Workers rows whose cells don't match the header, so their State is unread:"
                      " review (pilot).", ended.stderr)
        self.assertIn(f"## Goal\n\nParked {TODAY}: p\nFollow-ups:\n- lockfile risk\n  wraps here\n\n- stray rows\n"
                      "* starred\n1. numbered\nunindented tail\n\n"
                      "## Phases\n", self.text())
        self.assertIn("| review (pilot) | <t3-thread://v2/e/r> · task t1 | — | done | report written |\n", self.text())
        self.assertIn("## Queue (cards for the user)\n\n- c1\n\n## Learnings\n\n## Listening", self.text())

    def test_a_proof_inside_follow_ups_leaves_a_parked_project_parked(self):
        (self.dir / "project.md").write_text(PROJECT.replace("Follow-ups: none\n", "Follow-ups:\n- report\nProof: report received\n"))
        self.project("phase", "audit", "--result", "five reports", "--park", "later")
        self.project("phase", "again", "--result", "r", "--park", "later", code=1)
        self.project("start", *NEXT)

    def test_a_running_goal_that_starts_with_parked_is_running(self):
        self.project("phase", "audit", "--result", "five reports", "--goal", "Parked work is ready.", "--proof", "p")
        self.project("start", *NEXT, code=1)
        self.project("phase", "review", "--result", "r", "--park", "later")

    def test_an_archive_is_no_wider_than_its_source(self):
        (self.dir / "project.md").chmod(0o600)
        self.project("phase", "audit", "--result", "five reports", *NEXT)
        self.assertEqual((self.dir / "phases/01-audit.md").stat().st_mode & 0o777, 0o600)

    def test_a_reused_archive_narrows_to_its_source(self):
        (self.dir / "phases").mkdir()
        (self.dir / "phases/01-audit.md").write_text(PROJECT)
        (self.dir / "phases/01-audit.md").chmod(0o644)
        (self.dir / "project.md").chmod(0o600)
        self.project("phase", "audit", "--result", "five reports", *NEXT)
        self.assertEqual((self.dir / "phases/01-audit.md").stat().st_mode & 0o777, 0o600)

    def test_a_refused_phase_leaves_every_file_untouched(self):
        for args, code in [(["Bad_Slug", "--result", "r", *NEXT], 1),
                           (["audit", "--result", "two\nlines", *NEXT], 1),
                           (["audit", "--result", "ok\r## Listening", *NEXT], 1),
                           (["audit", "--result", "r", "--goal", "g", "--proof", "a\nb"], 1),
                           (["audit", "--result", "r", "--park", "p", "--goal", "g"], 2),
                           (["audit", "--result", "r", "--goal", "g"], 2),
                           (["audit", "--result", "r", "--proof", "p", "--park", "x"], 2)]:
            with self.subTest(args=args):
                self.project("phase", *args, code=code)
                self.assertEqual((self.text(), self.files()), (PROJECT, ["project.md"]))


if __name__ == "__main__":
    unittest.main()

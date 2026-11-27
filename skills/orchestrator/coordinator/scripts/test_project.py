"""project.py on a project.md shaped like a real coordinator's: blank lines between some
decisions, a Result section, notes under the Workers table, and a learning that runs
into the Listening heading. Each edit changes only its own lines.
Run: python3 -m unittest discover -s coordinator/scripts"""
import pathlib, subprocess, sys, tempfile, unittest
import project_md
from datetime import date

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


class Pulls(unittest.TestCase):
    """project_md.pulls, the one reader of a Branch or PR cell, on cells coordinators wrote."""
    def test_refs_resolve_against_the_origin(self):
        cases = [("#20 → #21 → #27", ("acme/box#20", "acme/box#21", "acme/box#27")),
                 ("box#3, #3, acme/box#3", ("acme/box#3",)),  # the origin's own repo name, once
                 ("acme/tools#1 https://github.com/o/r/pull/4", ("acme/tools#1", "o/r#4")),
                 ("#20–#22", ("acme/box#20", "acme/box#21", "acme/box#22")),
                 ("#5 (stack #6301) · `fix-#12`", ("acme/box#5",))]  # a note and a branch name no PR
        for text, refs in cases:
            with self.subTest(text):
                self.assertEqual(project_md.pulls(text, "acme/box"), project_md.Pulls(refs, ()))

    def test_a_ref_with_no_repo_to_resolve_against_is_unread(self):
        cases = [("tools #109 → #110 (#108 merged)", "acme/box", ("acme/box#110",), ("tools #109",)),
                 ("web #20–#22", "acme/box", (), ("web #20–#22",)),
                 ("tools#4", "acme/box", (), ("tools#4",)),  # its owner is a guess
                 ("#7 and box#8", "", (), ("#7", "box#8"))]
        for text, origin, refs, unread in cases:
            with self.subTest(text):
                self.assertEqual(project_md.pulls(text, origin), project_md.Pulls(refs, unread))


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

"""Tests for scope_judge.py on fixtures: a T3 database with the real tables' columns, a
GitHub search result and diff, and judge replies."""
import contextlib, io, json, sqlite3, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scope_judge  # noqa: E402

SCHEMA = """
CREATE TABLE orchestration_v2_projection_threads (
  thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, interaction_mode TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_messages (
  message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT, node_id TEXT, role TEXT NOT NULL,
  streaming INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
"""
PLAN = "✅ **Planning is done.**\n\n**Decisions**\n\n1. Export as one line\n\n**Not in scope**\n\n- VAT\n"
PLAN_REPLY = PLAN + "\n---\n\n**Next**\n\n- **`a` → build it**\n\n<!-- turn {\"state\":\"stop\"} -->"
OPENED, MERGED = "2026-10-26T08:00:00Z", "2026-10-28T08:00:00Z"
DIFF = """diff --git a/src/export.ts b/src/export.ts
index 1..2 100644
--- a/src/export.ts
+++ b/src/export.ts
@@ -1,3 +1,4 @@ export
 const a = 1
-const b = 2
+const b = 3
+const c = 4
@@ -10,2 +11,3 @@ more
 x
+y
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
--- a/pnpm-lock.yaml
+++ b/pnpm-lock.yaml
@@ -1 +1 @@
-old
+new
diff --git a/docs/a.md b/docs/a.md
--- a/docs/a.md
+++ b/docs/a.md
@@ -1 +1,2 @@
 title
+line
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        db_path = self.home / ".t3/userdata/statev2.sqlite"
        db_path.parent.mkdir(parents=True)
        self.db_path, self.n = db_path, 0
        with contextlib.closing(sqlite3.connect(db_path)) as db, db:
            db.executescript(SCHEMA)

    def tearDown(self):
        self.tmp.cleanup()

    def thread(self, thread_id, by="agent", parent=None, branch=None, mode="default", created="2026-10-20T00:00:00Z",
               prs=()):
        payload = {"createdBy": by, "branch": branch, "lineage": {"parentThreadId": parent},
                   "pullRequests": [{"repository": repo, "number": n} for repo, n in prs]}
        with contextlib.closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("insert into orchestration_v2_projection_threads values (?, 'p', 't', ?, ?, ?, ?)",
                       (thread_id, mode, created, created, json.dumps(payload)))

    def message(self, thread_id, role, at, text):
        self.n += 1
        with contextlib.closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("insert into orchestration_v2_projection_messages values (?, ?, null, null, ?, 0, ?, ?, ?)",
                       (f"m{self.n}", thread_id, role, at, at, json.dumps({"text": text})))

    def plans(self, branch="feat/x", key="o/r#5"):
        return scope_judge.dump([[key, OPENED, MERGED, branch]], home=str(self.home))[key]


class Dump(Fixture):
    def test_a_plan_in_an_ancestor_of_the_branch_thread(self):
        self.thread("root", by="user")
        self.message("root", "user", "2026-10-21T00:00:00Z", "plan simple mode")
        self.message("root", "assistant", "2026-10-22T00:00:00Z", PLAN_REPLY)
        self.message("root", "assistant", "2026-10-27T00:00:00Z", PLAN.replace("one line", "two lines"))
        self.thread("writer", parent="root", branch="feat/x")
        self.message("writer", "user", "2026-10-23T00:00:00Z", "Build layer 1 of the plan.")
        found = self.plans()
        # Nearest first: the writer's own brief comes before its parent's plan.
        self.assertEqual((found["kind"], found["thread"], found["source"]), ("brief", "writer", "branch"))
        self.thread("planner", by="user", branch="feat/x")
        self.message("planner", "assistant", "2026-10-22T00:00:00Z", PLAN_REPLY)
        found = self.plans()
        # A plan on the branch's own level beats a brief there, and loses its Next and turn blocks.
        self.assertEqual((found["kind"], found["thread"], found["text"]), ("plan", "planner", PLAN.strip()))

    def test_only_messages_before_the_pr_opened_count(self):
        self.thread("t", by="user", branch="feat/x")
        self.message("t", "assistant", "2026-10-27T00:00:00Z", PLAN)
        self.assertIsNone(self.plans())

    def test_the_ancestor_plan_when_the_branch_thread_has_no_brief(self):
        self.thread("root", by="user")
        self.message("root", "assistant", "2026-10-22T00:00:00Z", PLAN)
        self.thread("thread:provider:claudeAgent:native-thread:x", parent="root", branch="feat/x")
        self.message("thread:provider:claudeAgent:native-thread:x", "user", "2026-10-23T00:00:00Z", "/verify-work")
        self.thread("review", parent="root", branch="feat/x", mode="plan")
        self.message("review", "user", "2026-10-23T00:00:00Z", "Review this branch.")
        self.assertEqual(self.plans()["thread"], "root")

    def test_a_plan_needs_both_headings(self):
        self.thread("t", by="user", branch="feat/x")
        self.message("t", "assistant", "2026-10-22T00:00:00Z", "**Decisions**\n\n1. ship it")
        self.assertIsNone(self.plans())
        self.message("t", "assistant", "2026-10-22T01:00:00Z", "- **Building**: a\n- **Not building**: b")
        self.assertEqual(self.plans()["kind"], "plan")

    def test_a_linking_worker_when_no_thread_holds_the_branch(self):
        self.thread("coordinator", by="user", prs=[("o/r", 5)])
        self.message("coordinator", "assistant", "2026-10-22T00:00:00Z", PLAN)
        self.assertIsNone(self.plans(branch="feat/upper"))
        self.thread("worker", parent="coordinator", prs=[("o/r", 5)])
        self.message("worker", "user", "2026-10-21T00:00:00Z", "Mode: personal\n\nBuild R2.")
        found = self.plans(branch="feat/upper")
        self.assertEqual((found["thread"], found["source"]), ("worker", "link"))

    def test_a_brief_takes_later_instructions_until_the_merge(self):
        self.thread("t", branch="feat/x")
        self.message("t", "user", "2026-10-21T00:00:00Z", "Research it; don't edit any repo.")
        self.message("t", "user", "2026-10-22T00:00:00Z", "Background command \"git commit\" completed (exit code 0)")
        self.message("t", "user", "2026-10-26T09:00:00Z", "Coordinator: also make the tower treat done as settled.")
        self.message("t", "user", "2026-10-29T00:00:00Z", "Coordinator: next, build the follow-up.")
        text = self.plans()["text"]
        self.assertIn("### Later instruction, 2026-10-26T09:00:00Z\n\nCoordinator: also make the tower", text)
        self.assertNotIn("Background command", text)
        self.assertNotIn("next, build the follow-up", text)

    def test_a_brief_file_is_inlined(self):
        brief = self.home / "brief.md"
        brief.write_text("## Goal\n\nFix the null.")
        self.thread("t", branch="feat/x")
        self.message("t", "user", "2026-10-21T00:00:00Z", f"Your brief is `{brief}`. Read it in full.")
        self.assertIn("Fix the null.", self.plans()["text"])

    def test_no_database_means_no_plan(self):
        self.assertEqual(scope_judge.dump([["o/r#5", OPENED, MERGED, "b"]], home=str(self.home / "none")), {"o/r#5": None})


class Packets(Fixture):
    def runner(self, cmd, stdin=None, timeout=None):
        if cmd[:3] == ["gh", "api", "graphql"]:
            nodes = [{"number": n, "createdAt": OPENED, "mergedAt": "2026-10-27T00:00:00Z", "headRefName": f"feat/{n}",
                      "url": f"https://github.com/o/r/pull/{n}", "repository": {"nameWithOwner": "o/r"}}
                     for n in (5, 6, 7)]
            return json.dumps({"data": {"search": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}})
        if cmd[:3] == ["gh", "pr", "diff"]:
            return DIFF
        if cmd[0] == "ssh":
            raise RuntimeError("ssh devbox exited 255: unreachable")
        raise AssertionError(cmd)

    def test_packets_are_blind_and_list_prs_without_a_plan(self):
        for n in (5, 6):
            self.thread(f"t{n}", branch=f"feat/{n}")
            self.message(f"t{n}", "user", "2026-10-21T00:00:00Z", f"Brief {n}: export as one line.")
        out = self.home / "week"
        manifest = scope_judge.packets("2026-10-26T00:00:00Z", "2026-11-02T00:00:00Z", out, limit=1,
                                       runner=self.runner, home=str(self.home))
        self.assertEqual(len(manifest["judged"]), 1)
        self.assertEqual(manifest["no plan"], ["https://github.com/o/r/pull/7"])
        self.assertEqual(manifest["failed"], ["devbox: ssh devbox exited 255: unreachable"])
        judged = manifest["judged"][0]
        self.assertEqual([(h["id"], h["path"], h["added"], h["removed"]) for h in judged["hunks"]],
                         [("h1", "src/export.ts", 2, 1), ("h2", "src/export.ts", 1, 0), ("h3", "docs/a.md", 1, 0)])
        packet = (out / f"{judged['id']}.md").read_text()
        self.assertIn("export as one line", packet)
        self.assertNotIn("pull/", packet)
        self.assertNotIn("feat/", packet)
        self.assertNotIn("pnpm-lock", packet)

    def test_sample_takes_one_per_plan_first(self):
        prs = [{"key": k} for k in ("a", "b", "c", "d")]
        plans = {"a": {"thread": "t1", "at": "1"}, "b": {"thread": "t1", "at": "1"},
                 "c": {"thread": "t2", "at": "1"}, "d": None}
        picked = scope_judge.sample(prs, plans, 2, "seed")
        self.assertEqual(len({plans[p["key"]]["thread"] for p in picked}), 2)
        self.assertEqual(len(scope_judge.sample(prs, plans, 5, "seed")), 3)


def write_week(directory, verdicts, number=5):
    directory.mkdir(parents=True, exist_ok=True)
    hunks = [{"id": f"h{n}", "path": f"f{n}.ts", "added": 4, "removed": 1} for n in range(1, len(verdicts) + 1)]
    manifest = {"judged": [{"id": "r-5", "url": f"https://github.com/o/r/pull/{number}", "plan": {}, "hunks": hunks}],
                "no plan": ["https://github.com/o/r/pull/7"], "too large": [], "failed": []}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    body = "".join(f"### h{n} · `f{n}.ts` · +4 −1\n\n```diff\n+line {n}\n```\n\n" for n in range(1, len(verdicts) + 1))
    (directory / "r-5.md").write_text(f"# Scope judge\n\n## Plan\n\nThe plan.\n\n## Diff\n\n{body}")
    entries = [{"id": f"h{n}", "verdict": v, "why": f"reason {n}", "not_in_scope": "VAT" if v == "out" else ""}
               for n, v in enumerate(verdicts, 1)]
    (directory / "r-5.reply").write_text("Here it is:\n```json\n" + json.dumps({"hunks": entries}) + "\n```\n")


class Score(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_metric_1_is_the_out_of_plan_share_and_uncalibrated_until_labeled(self):
        write_week(self.dir / "w", ["in", "out", "unsure", "in"])
        result = scope_judge.score(self.dir / "w")
        metric = result["1 scope creep"]
        self.assertEqual((metric["value"], metric["judged value"], metric["num"], metric["den"]), (None, 0.25, 5, 20))
        self.assertEqual((metric["state"], metric["prs judged"]), ("uncalibrated", 1))
        self.assertEqual(metric["hunks"], {"in": 2, "out": 1, "unsure": 1})
        self.assertEqual(result["out of plan"][0]["not in scope"], "VAT")
        self.assertIn("1 scope creep: 0.25 (5/20 lines), uncalibrated", scope_judge.text(result))

    def test_a_missing_reply_is_reported_not_counted(self):
        write_week(self.dir / "w", ["in"])
        (self.dir / "w/r-5.reply").write_text("I couldn't finish.")
        metric = scope_judge.score(self.dir / "w")["1 scope creep"]
        self.assertEqual((metric["den"], metric["prs judged"]), (0, 0))
        self.assertIn("no JSON object with hunks", metric["failed"][0])

    def test_calibration_counts_once_8_of_10_agree(self):
        write_week(self.dir / "cal", ["in", "out"] * 8)
        cal = self.dir / "calibration.json"
        picked = scope_judge.calibrate([self.dir / "cal"], cal)
        self.assertEqual(len(picked), 10)
        self.assertEqual(sum(h["judge"] == "out" for h in picked), 5)
        listing = cal.with_suffix(".md").read_text()
        self.assertIn("## 10. https://github.com/o/r/pull/5", listing)
        self.assertNotIn('"judge"', listing)
        judge = [h["judge"] for h in json.loads(cal.read_text())["hunks"]]
        self.assertEqual(scope_judge.calibrated(cal)[0], "uncalibrated")
        flip = {"in": "out", "out": "in"}
        answer = ", ".join(f"{n} {j if n > 2 else flip[j]}" for n, j in enumerate(judge, 1))
        self.assertEqual(scope_judge.label(cal, answer), ("calibrated", "judge agrees on 8/10"))
        answer = ", ".join(f"{n} {'unsure' if n <= 3 else j}" for n, j in enumerate(judge, 1))
        self.assertEqual(scope_judge.label(cal, answer), ("failed calibration", "judge agrees on 7/10"))
        with self.assertRaisesRegex(ValueError, "no hunk 11: label 1 to 10"):
            scope_judge.label(cal, "11 out")
        write_week(self.dir / "w", ["out", "in"])
        scope_judge.label(cal, ", ".join(f"{n} {j}" for n, j in enumerate(judge, 1)))
        self.assertEqual(scope_judge.score(self.dir / "w", cal)["1 scope creep"]["value"], 0.5)

    def test_calibration_spreads_across_prs_and_skips_tiny_hunks(self):
        write_week(self.dir / "big", ["in", "out"] * 20, number=5)
        write_week(self.dir / "small", ["in", "out"], number=6)
        manifest = json.loads((self.dir / "small/manifest.json").read_text())
        manifest["judged"][0]["hunks"][1]["added"] = 1
        (self.dir / "small/manifest.json").write_text(json.dumps(manifest))
        picked = scope_judge.calibrate([self.dir / "big", self.dir / "small"], self.dir / "c.json")
        self.assertEqual([h["hunk"] for h in picked if h["pr"].endswith("/6")], ["h1"])

    def test_main_prints_metric_1(self):
        write_week(self.dir / "w", ["in"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(scope_judge.main(["score", str(self.dir / "w"), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["1 scope creep"]["judged value"], 0.0)


if __name__ == "__main__":
    unittest.main()

"""Tests for scorecard.py on fixtures: a T3 database with the real tables' columns,
verify-work stores, Claude transcripts, GitHub search results, and a real git repo for
the patch-id join."""
import contextlib, json, os, sqlite3, subprocess, sys, tempfile, unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit_path  # noqa: E402
sys.path.insert(0, str(kit_path.tool() / "hooks"))
import scorecard  # noqa: E402
import verdicts  # noqa: E402

START, END = "2026-10-18T22:00:00Z", "2026-10-25T23:00:00Z"
SCHEMA = """
CREATE TABLE orchestration_v2_projection_threads (
  thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE orchestration_v2_projection_messages (
  message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT, node_id TEXT, role TEXT NOT NULL,
  streaming INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
"""


def verdict_row(patch, at, verdict="done", branch="", version="v3", verifier="work-verifier", head="h", base="b",
                findings=()):
    if version == "v2":
        return "\t".join([patch, head, base, at, "v2", "s", "a", verifier])
    body = {"verdict": verdict, "evidence": {}, "findings": list(findings), **({"branch": branch} if branch else {})}
    return "\t".join([patch, head, base, at, "v3", "s", "a", verifier, json.dumps(body)])


def transcript_lines(*entries):
    return "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in entries)


def tool_use(tool_id, at):
    return {"type": "assistant", "timestamp": at,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}}]}}


def denial(tool_id, at, reason="Load the skill first"):
    return {"type": "user", "timestamp": at, "message": {"content": [
        {"type": "tool_result", "content": f"PreToolUse:Bash hook error: {reason}", "is_error": True,
         "tool_use_id": tool_id}]}}


class Dump(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_messages_keep_typed_and_slack_asks_only(self):
        db_path = self.home / ".t3/userdata/statev2.sqlite"
        db_path.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(db_path)) as db, db:
            db.executescript(SCHEMA)
            for thread in ("t1", "import:x"):
                db.execute("insert into orchestration_v2_projection_threads values (?, 'p', 'Title', '', '', '{}')",
                           (thread,))
            for n, (thread, role, at, by, text) in enumerate([
                    ("t1", "user", "2026-10-20T08:00:00.000Z", "user", "this is wrong again"),
                    ("t1", "user", "2026-10-20T09:00:00.000Z", "agent", "Slack #dev: x\nOliver's ask: keep it minimal"),
                    ("t1", "user", "2026-10-20T10:00:00.000Z", "agent", "Update on pull request #1"),
                    ("t1", "assistant", "2026-10-20T10:00:00.000Z", None, "a reply"),
                    ("import:x", "user", "2026-10-20T11:00:00.000Z", "user", "replayed prompt"),
                    ("t1", "user", "2026-10-26T08:00:00.000Z", "user", "next week")]):
                db.execute("insert into orchestration_v2_projection_messages values (?, ?, null, null, ?, 0, ?, ?, ?)",
                           (f"m{n}", thread, role, at, at, json.dumps({"createdBy": by, "text": text})))
        rows = scorecard.dump(START, END, self.home)["messages"]
        self.assertEqual([(r[3], r[4]) for r in rows], [("user", "this is wrong again"), ("slack", "keep it minimal")])

    def test_verdicts_read_every_store_as_verdicts_py_does(self):
        store = self.home / "Developer/work/franklin/franklin-next/.git/verify-work/verdicts.tsv"
        store.parent.mkdir(parents=True)
        store.write_text("\n".join([
            verdict_row("p1", "2026-10-19T00:00:00Z", version="v2", head="h1"),
            verdict_row("p2", "2026-10-20T00:00:00Z", "not-done", "feat/a", head="h2", findings=[
                "1 · Blocker · it throws · a.ts:3 → fix", "2 · Cleanup · rename · a.ts:9 → fix", "no label"]),
            verdict_row("p3", "2026-10-20T00:00:00Z", verifier="someone-else"),
            "p4\th\tb\t2026-10-20T00:00:00Z\tv3\ts\ta\twork-verifier\t{not json",
            "p5\th\tb\t2026-10-20T00:00:00Z"]) + "\n")
        self.assertEqual(scorecard.dump(START, END, self.home)["verdicts"], {"franklin-next": [
            ["p1", "2026-10-19T00:00:00Z", "done", "~b..h1", None],
            # No git history to read here, so feat/a's first verdict can't be proven first.
            ["p2", "2026-10-20T00:00:00Z", "not-done", "~feat/a", {"Blocker": 1, "Cleanup": 1, "unlabeled": 1}]]})

    def test_verdicts_skip_review_loop_results(self):
        # review-loop records through hooks/verdicts.py into the same store; those rows aren't verdicts.
        repo = self.home / "Developer/repo"
        repo.mkdir(parents=True)
        env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        heads = []
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
        for name in ("base", "feat"):
            (repo / name).write_text(name)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
            subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", name],
                           check=True, env=env)
            heads.append(git(repo, "rev-parse", "HEAD"))
        subprocess.run([sys.executable, str(kit_path.tool() / "hooks" / "verdicts.py"), "review", *heads,
                        "--rounds", "1"], cwd=repo, env=env, check=True, capture_output=True)
        self.assertEqual(scorecard.verdicts(self.home).get("repo", []), [])
        with open(repo / ".git" / "verify-work" / "verdicts.tsv", "a") as f:
            f.write("p\th\tb\t2026-11-05T00:00:00Z\tv2\ts\ta\twork-verifier\n")  # one it does read
        self.assertEqual(len(scorecard.verdicts(self.home)["repo"]), 1)

    def test_tool_calls_count_each_id_once_by_hour_inside_the_window(self):
        session = self.home / ".claude/projects/repo/s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(transcript_lines(
            tool_use("toolu_1", "2026-10-20T08:05:00.000Z"), denial("toolu_1", "2026-10-20T08:05:01.000Z"),
            tool_use("toolu_2", "2026-10-20T09:00:00.000Z"),
            denial("toolu_2", "2026-10-20T09:00:01.000Z", 'merge-gate failed: ✗ branch "main"'),
            tool_use("toolu_old", "2026-10-10T09:00:00.000Z")))
        # A resumed session copies the earlier entries into its own file.
        (session.parent / "resumed.jsonl").write_text(session.read_text())
        self.assertEqual(scorecard.dump(START, END, self.home)["tools"],
                         {"2026-10-20T08": [1, 1], "2026-10-20T09": [1, 1]})

    def test_missing_sources_dump_empty(self):
        self.assertEqual(scorecard.dump(START, END, self.home), {"messages": [], "verdicts": {}, "tools": {}})


def thread(login, kind="User", body="text"):
    return {"comments": {"nodes": [{"author": {"login": login, "__typename": kind}, "body": body}]}}


PICTURE_MAJOR = '**<picture><img src="major-16.svg" alt=""></picture> Major** · **Security**'
EMOJI_CRITICAL = "**🎯 Functional Correctness** | **🔴 Critical** | **⚡ Quick win**"
EMOJI_MINOR = "**🎯 Functional Correctness** | **🟡 Minor** | **⚡ Quick win**"


class Defects(unittest.TestCase):
    def test_counts_severe_coderabbit_and_teammate_threads_per_pr(self):
        prs = [{"reviewThreads": {"nodes": [
                    thread("coderabbitai", "Bot", PICTURE_MAJOR), thread("coderabbitai", "Bot", EMOJI_MINOR),
                    thread("cubic-dev-ai", "Bot", "**P1** Major issue"), thread("CasperEngl"),
                    thread(scorecard.LOGIN), {"comments": {"nodes": []}}]}},
               {"reviewThreads": {"nodes": [thread("coderabbitai", "Bot", EMOJI_CRITICAL), thread("anderrodsan")]}}]
        found = scorecard.defects(prs)
        self.assertEqual(found["2 CodeRabbit Major or Critical per PR"], {"value": 1.0, "num": 2, "den": 2})
        self.assertEqual(found["2 teammate threads per PR"], {"value": 1.0, "num": 2, "den": 2})
        self.assertIn("not measured", found[scorecard.FIXES])

    def test_no_prs_has_no_rate(self):
        self.assertIsNone(scorecard.defects([])["2 teammate threads per PR"]["value"])


class Corrections(unittest.TestCase):
    def test_counts_theme_messages_once_per_minute_and_skips_bare_picks(self):
        rows = [["2026-10-20T08:00:10Z", "t", "", "user", "you did this wrong again"],
                ["2026-10-20T08:00:50Z", "t", "", "user", "you did this wrong again"],  # the other machine
                ["2026-10-20T08:01:00Z", "t", "", "user", "what is the most idiomatic fix?"],
                ["2026-10-20T08:02:00Z", "t", "", "user", "a"],
                ["2026-10-20T08:03:00Z", "t", "", "user", "/compact keep the wrong parts"],
                ["2026-10-20T08:04:00Z", "t", "", "user", "ship it"],
                ["2026-10-20T08:05:00Z", "t", "", "slack", "make a follow-up PR"],
                ["2026-10-27T08:00:00Z", "t", "", "user", "wrong again, next week"]]
        found = scorecard.corrections(rows, 4, START, END)["3 corrections per merged PR"]
        self.assertEqual((found["num"], found["den"], found["value"]), (3, 4, 0.75))
        self.assertEqual(found["detail"], {"correction": 1, "scope": 1, "quality-bar": 1, "messages": 4})


class Rework(unittest.TestCase):
    def test_a_branch_counts_in_the_window_of_its_first_verdict_ever(self):
        stores = {"franklin-next": [
            ["p1", "2026-10-20T00:00:00Z", "done", "a", {}],
            ["p2", "2026-10-21T00:00:00Z", "not-done", "b", {"Blocker": 2}],
            ["p3", "2026-10-22T00:00:00Z", "done", "b", {}],
            ["p4", "2026-10-10T00:00:00Z", "not-done", "c", {"Blocker": 5}],  # first verified the week before
            ["p5", "2026-10-21T00:00:00Z", "done", "c", {}],
            ["p6", "2026-10-21T00:00:00Z", "done", "~base..head", {}]],  # first verdict unknown
            "skills": [["p7", "2026-10-23T00:00:00Z", "not-done", "a", {"Blocker": 1, "Optional": 1}]]}
        found = scorecard.rework(stores, START, END)
        self.assertEqual(found["4 first-pass Done: franklin-next"], {"value": 0.5, "num": 1, "den": 2})
        self.assertEqual(found["4 first-pass Done: all repos"]["num"], 1)
        self.assertEqual(found["4 first-pass Done: all repos"]["detail"],
                         {"franklin-next": "1/2", "skills": "0/1", "left out": 1})
        self.assertEqual(found["4 Not done findings, all repos"]["value"], 4)
        self.assertEqual(found["4 Not done findings, all repos"]["detail"], {"Blocker": 3, "Optional": 1})

    def test_a_window_with_no_known_first_verdict_or_before_full_records_is_not_measured(self):
        stores = {"franklin-next": [["p1", "2026-10-20T00:00:00Z", "done", "~a..b", None],
                                    ["p2", "2026-10-21T00:00:00Z", "not-done", "~x", {"Blocker": 1}]]}
        found = scorecard.rework(stores, START, END)
        for name in ("4 first-pass Done: franklin-next", "4 first-pass Done: all repos",
                     "4 Not done findings, all repos"):
            self.assertIn("not measured", found[name])
        self.assertIn("2026-10-21", found["4 Not done findings, all repos"]["not measured"])
        self.assertEqual(found["4 first-pass Done: all repos"]["detail"], {"left out": 2})


def git(repo, *args):
    """git in repo, never signing, whatever the runner's config asks."""
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class Lineages(unittest.TestCase):
    """Verdicts recorded without a branch join the branch their head descends into."""

    def test_unnamed_verdicts_join_their_branch_by_base_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "develop")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "T")
            heads = {}
            for name in ("base", "a1", "a2", "b1"):
                if name == "b1":
                    git(repo, "checkout", "-q", "-b", "b", heads["base"])
                (repo / f"{name}.txt").write_text(name)
                git(repo, "add", ".")
                git(repo, "commit", "-qm", name)
                heads[name] = git(repo, "rev-parse", "HEAD")
            base = heads["base"]
            rows = [["p1", heads["a1"], base, "2026-10-20T01:00:00Z", "not-done", "", {}],  # before branch names
                    ["p2", heads["a2"], base, "2026-10-20T02:00:00Z", "done", "feat/a", {}],
                    ["p3", heads["b1"], base, "2026-10-20T03:00:00Z", "done", "", {}],  # same base, other history
                    ["p4", heads["a1"], heads["a1"], "2026-10-20T04:00:00Z", "done", "", {}],  # new base and diff
                    ["p3", "f" * 40, "e" * 40, "2026-10-20T05:00:00Z", "done", "", {}]]  # b, cleanly rebased
            self.assertEqual(scorecard.lineages(repo, rows),
                             ["feat/a", "feat/a", f"~{base[:10]}..{heads['b1'][:10]}",
                              f"~{heads['a1'][:10]}..{heads['a1'][:10]}", f"~{base[:10]}..{heads['b1'][:10]}"])


class Unproven(unittest.TestCase):
    """A named chain's first verdict may not be the first on its commits when they predate
    the store's branch names, or an earlier verdict naming no branch covered one of them."""

    def test_marks_chains_with_older_commits_or_an_earlier_unnamed_verdict_on_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "develop")
            heads = {}
            # x2 rewrites x onto old: a new commit with the same change.
            for name, parent, day in (("base", None, "20"), ("old", None, "24"), ("new", None, "27"),
                                      ("x", None, "28"), ("x2", "old", "28")):
                if parent:
                    git(repo, "checkout", "-q", "-b", name, heads[parent])
                env = {**os.environ, "GIT_AUTHOR_DATE": f"2026-10-{day}T12:00:00+02:00",
                       "GIT_COMMITTER_DATE": f"2026-10-{day}T12:00:00+02:00", "GIT_AUTHOR_NAME": "T",
                       "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T",
                       "GIT_COMMITTER_EMAIL": "t@example.com"}
                (repo / f"{name.rstrip('2')}.txt").write_text(name.rstrip("2"))
                subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
                subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", name],
                               check=True, env=env)
                heads[name] = git(repo, "rev-parse", "HEAD")
            rows = [["p1", heads["old"], heads["base"], "2026-10-26T08:00:00Z", "done", "restacked", {}],
                    ["p2", heads["new"], heads["old"], "2026-10-28T08:00:00Z", "done", "fresh", {}],
                    ["p3", "f" * 40, heads["base"], "2026-10-28T09:00:00Z", "done", "unreadable", {}],
                    ["p4", heads["new"], heads["base"], "2026-10-25T08:00:00Z", "not-done", "", {}],
                    ["p5", heads["x"], heads["new"], "2026-10-28T10:00:00Z", "not-done", "", {}],  # detached HEAD
                    ["p6", heads["x2"], heads["old"], "2026-10-28T11:00:00Z", "done", "rewritten", {}],
                    # An unnamed verdict on fresh's commit after fresh's first doesn't change its first.
                    ["p7", heads["new"], heads["old"], "2026-10-29T08:00:00Z", "not-done", "", {}]]
            names = ["restacked", "fresh", "unreadable", "~chain", "~x", "rewritten", "~late"]
            self.assertEqual(scorecard.unproven(repo, rows, names),
                             ["~restacked", "fresh", "~unreadable", "~chain", "~x", "~rewritten", "~late"])


class Coverage(unittest.TestCase):
    """A squash merge's patch-id matches the verdict recorded on its branch's diff."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        repo = self.repo = Path(self.tmp.name)
        git(repo, "init", "-q", "-b", "develop")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "T")
        (repo / "a.txt").write_text("one\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "base")
        self.base = git(repo, "rev-parse", "HEAD")
        self.squashes = {}
        for name in ("verified", "unverified", "rejected"):
            git(repo, "checkout", "-qb", name, self.base)
            (repo / f"{name}.txt").write_text(f"{name}\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", name)
            head = git(repo, "rev-parse", "HEAD")
            setattr(self, name, verdicts._patch_id(repo, verdicts.diff(repo, self.base, head)))
            git(repo, "checkout", "-q", "develop")
            git(repo, "merge", "-q", "--squash", name)
            git(repo, "commit", "-qm", f"{name} (#1)")
            self.squashes[name] = git(repo, "rev-parse", "HEAD")
        git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        git(repo, "checkout", "-q", "-b", "effect-v4", self.base)
        (repo / "side.txt").write_text("side\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "side")
        self.side = git(repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_merges_on_develop_whose_latest_verdict_is_done(self):
        # A later Not done revokes a Done, whatever order the rows were read in.
        rows = [[self.verified, "2026-10-21T00:00:00Z", "done", "verified", {}],
                [self.rejected, "2026-10-21T00:00:00Z", "not-done", "rejected", {"Blocker": 1}],
                [self.rejected, "2026-10-20T00:00:00Z", "done", "rejected", {}]]
        prs = [{"number": n, "mergeCommit": {"oid": self.squashes[name]}}
               for n, name in ((1, "verified"), (2, "unverified"), (3, "rejected"))]
        prs += [{"number": 4, "mergeCommit": {"oid": self.side}},  # merged into another base
                {"number": 5, "mergeCommit": {"oid": "f" * 40}},  # not fetched
                {"number": 6, "mergeCommit": None}]
        found = scorecard.coverage(prs, rows, str(self.repo))["5 Done on merged develop diff"]
        self.assertEqual((found["num"], found["den"]), (1, 3))
        self.assertEqual(found["detail"], {"no verdict": [2], "commit not in clone": [5]})


class KitCost(unittest.TestCase):
    def test_counts_always_loaded_words_skill_words_and_code_without_tests(self):
        files = {"router.md": "one two three", "reply-shape/SKILL.md": "---\nname: x\n---\nfour five",
                 "build/SKILL.md": "---\nname: build\n---\nsix", "build/references/r.md": "not counted",
                 "hooks/a.py": "1\n2\n", "hooks/test_a.py": "1\n2\n3\n", "scripts/b.sh": "1\n"}
        found = scorecard.kit_cost("abcdef1234567", files, [200, 3])
        self.assertEqual(found["6 always-loaded words (Claude)"]["value"], 5)
        self.assertEqual(found["6 SKILL.md words"]["value"], 11)  # frontmatter too, as measure.py counts
        self.assertEqual(found["6 kit code lines (no tests)"]["value"], 3)
        self.assertEqual(found["6 hook denials per 100 tool calls"]["value"], 1.5)

    def test_leaves_out_the_evals_and_maintainer_folders(self):
        files = {"hooks/a.py": "1\n", "maintainer/evals.py": "1\n2\n", "evals/x/setup.sh": "1\n",
                 "evals/x/fixtures/SKILL.md": "seven eight"}
        found = scorecard.kit_cost("abcdef1234567", files, [200, 3])
        self.assertEqual(found["6 kit code lines (no tests)"]["value"], 1)
        self.assertEqual(found["6 SKILL.md words"]["value"], 0)

    def test_a_kit_without_instruction_files_reports_always_loaded_words_as_not_measured(self):
        files = {"skills/optional/reply-shape/SKILL.md": "---\nname: x\n---\nfour five"}
        found = scorecard.kit_cost("abcdef1234567", files, [200, 3])["6 always-loaded words (Claude)"]
        self.assertEqual((found["value"], found["not measured"]), (None, scorecard.NO_INSTRUCTIONS))


class Windows(unittest.TestCase):
    def test_a_week_runs_local_midnight_to_midnight_across_the_dst_change(self):
        self.assertEqual(scorecard.window(date(2026, 10, 19), 7), ("2026-10-18T22:00:00Z", "2026-10-25T23:00:00Z"))
        self.assertEqual(scorecard.window(date(2026, 10, 26), 7), ("2026-10-25T23:00:00Z", "2026-11-01T23:00:00Z"))

    def test_score_sums_only_the_windows_hours(self):
        machines = {"mac": {"messages": [], "verdicts": {}, "tools": {
                        "2026-10-18T21": [50, 5], "2026-10-18T22": [10, 1], "2026-10-25T22": [10, 0]}},
                    "devbox": {"messages": [], "verdicts": {}, "tools": {"2026-10-25T23": [99, 9]}}}
        found = scorecard.score(START, END, machines, {"franklin": [], "merged": 0}, ("rev", {}), "/nowhere")
        self.assertEqual(found["6 hook denials per 100 tool calls"]["num"], 1)
        self.assertEqual(found["6 hook denials per 100 tool calls"]["den"], 20)
        self.assertEqual(found[scorecard.SCOPE]["value"], None)


class GitHub(unittest.TestCase):
    def test_search_follows_pages_and_fetch_keeps_merges_inside_the_window(self):
        pages = iter([{"nodes": [{"number": 1, "mergedAt": "2026-10-20T00:00:00Z"}, {}],
                       "pageInfo": {"hasNextPage": True, "endCursor": "c1"}},
                      {"nodes": [{"number": 2, "mergedAt": "2026-10-26T00:00:00Z"}],
                       "pageInfo": {"hasNextPage": False, "endCursor": None}}])
        calls = []

        def runner(cmd, **_):
            calls.append(cmd)
            page = next(pages, None) or {"nodes": [], "pageInfo": {"hasNextPage": False}}
            return json.dumps({"data": {"search": {"issueCount": 0, **page}}})

        found = scorecard.fetch_github(START, END, runner)
        self.assertEqual([pr["number"] for pr in found["franklin"]], [1])
        self.assertEqual(found["merged"], 0)
        self.assertIn("after=c1", calls[1])
        self.assertIn(f"q=repo:{scorecard.FRANKLIN} is:pr is:merged author:{scorecard.LOGIN} merged:{START}..{END}",
                      calls[0])


class Report(unittest.TestCase):
    def test_gather_names_a_machine_it_couldnt_read(self):
        def runner(cmd, **_):
            raise RuntimeError("ssh exited 255: timed out")

        with tempfile.TemporaryDirectory() as home:
            machines, failed = scorecard.gather(START, END, ["devbox"], runner, home)
        self.assertEqual(list(machines), ["mac"])
        self.assertEqual(failed, ["devbox: ssh exited 255: timed out"])

    def test_table_prints_not_measured_rows_and_details(self):
        metrics = {scorecard.SCOPE: {"value": None, "not measured": "why"},
                   "4 Not done findings, all repos": {"value": None, "not measured": "only Done"},
                   "5 Done on merged develop diff": {"value": 0.4, "num": 17, "den": 42, "detail": {"no verdict": [9]}},
                   "6 SKILL.md words": {"value": 29680, "num": 29680, "den": None},
                   "4 first-pass Done: franklin-next": {"value": None, "num": 0, "den": 0}}
        out = scorecard.table([{"label": "w1", "metrics": metrics, "failed": ["devbox: down"]}])
        self.assertIn("| 1 scope creep | not measured |", out)
        self.assertIn("- **1 scope creep**: not measured: why.", out)
        self.assertIn("- **4 Not done findings, all repos**: not measured: only Done.", out)
        self.assertIn("| 5 Done on merged develop diff | 0.40 (17/42) |", out)
        self.assertIn("| 6 SKILL.md words | 29,680 |", out)
        self.assertIn("| 4 first-pass Done: franklin-next | n/a (0) |", out)
        self.assertIn("- **5 Done on merged develop diff**, w1: {'no verdict': [9]}", out)
        self.assertIn("- **Unread machine**: devbox: down", out)



class KitRev(unittest.TestCase):
    """The kit's metrics come from the kit checkout's origin/main as of the window's end."""

    def runner(self, rev):
        return lambda argv, **_: rev

    def test_uses_the_kit_checkouts_last_commit_before_the_end(self):
        self.assertEqual(scorecard.kit_rev("2030-01-01", Path("/kit"), self.runner("k1\n")), "k1")

    def test_a_window_before_the_kits_repo_is_refused_naming_the_workshop_commit(self):
        with self.assertRaises(SystemExit) as raised:
            scorecard.kit_rev("2026-01-01", Path("/kit"), self.runner(""))
        self.assertIn("olivercederborg/skills at 394f6d52", str(raised.exception))

if __name__ == "__main__":
    unittest.main()

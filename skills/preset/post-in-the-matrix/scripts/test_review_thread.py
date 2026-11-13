import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_thread  # noqa: E402

REPO = "hifranklin-tech/franklin-next"


def pr(number, source="agent", repo=REPO):
    return {"repository": repo, "number": number, "source": source, "state": "open"}


def thread(tid, title, prs=(), settled=False, updated="2026-11-13T10:00:00Z", parent=None):
    return {"threadId": tid, "title": title, "pullRequests": list(prs), "settled": settled,
            "updatedAt": updated, "parentThreadId": parent, "relationshipToParent": "subagent" if parent else None,
            "status": "waiting", "link": f"https://example.invalid/{tid}"}


def run(items, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(items, handle)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = review_thread.main([*args, "--list-json", handle.name])
    finally:
        os.unlink(handle.name)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()


class HolderTest(unittest.TestCase):
    def test_linked_thread_wins_over_title_and_stack(self):
        items = [thread("stack", "Review #5815 · other", [pr(5816, "stack")]),
                 thread("title", "Review #5816 · x"),
                 thread("own", "◎ #5816 · CasperEngl", [pr(5816)])]
        code, out, _ = run(items, REPO, "5816")
        self.assertEqual((code, out["thread"]["threadId"], out["thread"]["match"]), (0, "own", "linked"))

    def test_stack_neighbour_is_found_when_nothing_closer(self):
        items = [thread("t5815", "◎ #5815 · CasperEngl", [pr(5815), pr(5816, "stack")])]
        _, out, _ = run(items, REPO, "5816")
        self.assertEqual((out["thread"]["threadId"], out["thread"]["match"]), ("t5815", "stack"))

    def test_unlinked_old_thread_is_found_by_exact_title(self):
        items = [thread("old", "Review #5349 · [DEV-3082] Save the debit", settled=True)]
        _, out, _ = run(items, REPO, "5349")
        self.assertEqual((out["thread"]["threadId"], out["thread"]["match"], out["thread"]["settled"]),
                         ("old", "title", True))

    def test_title_number_must_end_there(self):
        items = [thread("long", "Review #5739 · x"), thread("pre", "Preview #57 · x")]
        _, out, _ = run(items, REPO, "57")
        self.assertIsNone(out["thread"])

    def test_subagents_and_dismissed_stack_links_never_count(self):
        items = [thread("child", "◎ #5815 · sub", [pr(5815)], parent="p"),
                 thread("dismissed", "Some work", [pr(5815, "stack-dismissed")])]
        _, out, _ = run(items, REPO, "5815")
        self.assertIsNone(out["thread"])

    def test_other_repo_with_same_number_is_not_this_pr(self):
        items = [thread("skills", "◎ #62 · jokklan", [pr(62, repo="hifranklin-tech/skills")])]
        _, out, _ = run(items, REPO, "62")
        self.assertEqual(out["thread"]["match"], "title")  # only the title says #62
        _, out, _ = run(items, "hifranklin-tech/skills", "62")
        self.assertEqual(out["thread"]["match"], "linked")

    def test_unsettled_beats_settled_then_newest(self):
        items = [thread("old-open", "Review #1 · a", [pr(1)], updated="2026-11-01T00:00:00Z"),
                 thread("new-settled", "Review #1 · b", [pr(1)], settled=True, updated="2026-11-12T00:00:00Z"),
                 thread("new-open", "Review #1 · c", [pr(1)], updated="2026-11-10T00:00:00Z")]
        _, out, _ = run(items, REPO, "1")
        self.assertEqual(out["thread"]["threadId"], "new-open")

    def test_repo_case_and_custom_prefix(self):
        items = [thread("t", "PR 42 review", [pr(42, repo="HiFranklin-Tech/Franklin-Next")])]
        _, out, _ = run(items, REPO, "42")
        self.assertEqual(out["thread"]["match"], "linked")
        _, out, _ = run([thread("t", "PR 42 review")], REPO, "42", "--title-prefix", "PR ")
        self.assertEqual(out["thread"]["match"], "title")

    def test_unreadable_t3_exits_2_without_output(self):
        with mock.patch.object(review_thread.subprocess, "run",
                               return_value=mock.Mock(returncode=1, stderr="server not running", stdout="")):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = review_thread.main([REPO, "1"])
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertIn("server not running", err.getvalue())

    def test_missing_t3_exits_2(self):
        with mock.patch.object(review_thread.subprocess, "run", side_effect=FileNotFoundError("t3")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(review_thread.main([REPO, "1"]), 2)

    def test_project_flag_is_passed_to_t3(self):
        with mock.patch.object(review_thread.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="[]", stderr="")) as called:
            with contextlib.redirect_stdout(io.StringIO()):
                review_thread.main([REPO, "1", "--project", "/repo"])
        self.assertEqual(called.call_args.args[0], ["t3", "thread", "list", "--json", "--project", "/repo"])


if __name__ == "__main__":
    unittest.main()

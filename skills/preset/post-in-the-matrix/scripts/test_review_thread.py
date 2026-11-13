import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_thread  # noqa: E402

REPO = "octo/app"


def pr(number, source="agent", repo=REPO, watching=False):
    return {"repository": repo, "number": number, "source": source, "state": "open", "watching": watching}


def thread(tid, title, prs=(), settled=False, updated="2026-11-13T10:00:00Z", relation=None, open_count=None):
    prs = list(prs)
    return {"threadId": tid, "title": title, "pullRequests": prs, "settled": settled, "updatedAt": updated,
            "parentThreadId": "p" if relation else None, "relationshipToParent": relation,
            "openPullRequestCount": len(prs) if open_count is None else open_count,
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


def found(items, number, *flags, repo=REPO):
    code, out, err = run(items, repo, str(number), *flags)
    assert code == 0, err
    return out["thread"]


class HolderTest(unittest.TestCase):
    def test_own_link_beats_title_and_stack(self):
        items = [thread("stack", "Review #5815 · a", [pr(5815), pr(5816, "stack")]),
                 thread("title", "Review #5816 · b"),
                 thread("own", "◎ #5816 · c", [pr(5816, watching=True)])]
        self.assertEqual((found(items, 5816)["threadId"], found(items, 5816)["match"],
                          found(items, 5816)["watching"]), ("own", "linked", True))

    def test_stack_neighbour_is_found_when_nothing_closer(self):
        items = [thread("t5815", "◎ #5815 · a", [pr(5815), pr(5816, "stack", watching=True)])]
        self.assertEqual((found(items, 5816)["threadId"], found(items, 5816)["match"]), ("t5815", "stack"))

    def test_unlinked_old_review_is_found_by_title(self):
        items = [thread("old", "Review #5349 · Save the debit", settled=True)]
        self.assertEqual((found(items, 5349)["match"], found(items, 5349)["settled"]), ("title", True))

    def test_only_review_threads_count(self):
        items = [thread("work", "Fix the export for #42", [pr(42)])]
        self.assertIsNone(found(items, 42))

    def test_title_number_must_end_at_a_word_boundary(self):
        items = [thread("long", "Review #5739 · x"), thread("word", "Review #57abc"), thread("pre", "Preview #57")]
        self.assertIsNone(found(items, 57))

    def test_subagents_never_count_but_forks_do(self):
        self.assertIsNone(found([thread("child", "◎ #1 · a", [pr(1)], relation="subagent")], 1))
        self.assertEqual(found([thread("fork", "◎ #1 · a", [pr(1)], relation="fork")], 1)["threadId"], "fork")

    def test_dismissed_stack_link_never_counts(self):
        self.assertIsNone(found([thread("t", "Review #9 · a", [pr(9), pr(1, "stack-dismissed")])], 1))

    def test_title_with_another_repos_link_is_not_this_pr(self):
        items = [thread("skills", "◎ #62 · a", [pr(62, repo="octo/skills")])]
        self.assertIsNone(found(items, 62))
        self.assertEqual(found(items, 62, repo="octo/skills")["match"], "linked")

    def test_unsettled_beats_settled_then_newest(self):
        items = [thread("old-open", "Review #1 · a", [pr(1)], updated="2026-11-01T00:00:00Z"),
                 thread("new-settled", "Review #1 · b", [pr(1)], settled=True, updated="2026-11-12T00:00:00Z"),
                 thread("new-open", "Review #1 · c", [pr(1)], updated="2026-11-10T00:00:00Z")]
        self.assertEqual(found(items, 1)["threadId"], "new-open")

    def test_repo_case_and_extra_prefix_keep_the_defaults(self):
        items = [thread("t", "Review #42 · a", [pr(42, repo="Octo/App")])]
        self.assertEqual(found(items, 42)["match"], "linked")
        items = [thread("custom", "PR 7 review"), thread("default", "Review #8 · a")]
        self.assertEqual(found(items, 7, "--title-prefix", "PR ")["threadId"], "custom")
        self.assertEqual(found(items, 8, "--title-prefix", "PR ")["threadId"], "default")

    def test_none_is_refused_when_a_review_thread_hides_links(self):
        code, out, err = run([thread("big", "◎ #1 · a", [pr(1)], open_count=6)], REPO, "2")
        self.assertEqual((code, out), (2, None))
        self.assertIn("big", err)

    def test_malformed_list_exits_2(self):
        self.assertEqual(run([None], REPO, "1")[0], 2)
        self.assertEqual(run({"threads": []}, REPO, "1")[0], 2)

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

    def test_a_full_page_with_no_holder_is_read_twice(self):
        page = [thread(f"t{i}", f"Work {i}") for i in range(100)]
        later = page + [thread("moved", "◎ #5 · a", [pr(5)])]
        replies = [mock.Mock(returncode=0, stdout=json.dumps(page), stderr=""),
                   mock.Mock(returncode=0, stdout=json.dumps(later), stderr="")]
        with mock.patch.object(review_thread.subprocess, "run", side_effect=replies) as called:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = review_thread.main([REPO, "5", "--project", "/repo"])
        self.assertEqual((code, json.loads(out.getvalue())["thread"]["threadId"]), (0, "moved"))
        self.assertEqual(called.call_args.args[0], ["t3", "thread", "list", "--json", "--project", "/repo"])


if __name__ == "__main__":
    unittest.main()

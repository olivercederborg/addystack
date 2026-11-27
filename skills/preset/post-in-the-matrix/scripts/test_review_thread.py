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


def listed(*prs):
    """A list_thread_pull_requests result holding these PRs."""
    return {"pullRequests": list(prs), "chains": [], "nextCursor": None}


def saved(data):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(data, handle)
    return handle.name


def run(items, *args, links=None):
    files = [saved(items)] + ([saved(links)] if links is not None else [])
    flags = ["--list-json", files[0]] + (["--links", files[1]] if links is not None else [])
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = review_thread.main([*args, *flags])
    finally:
        for name in files:
            os.unlink(name)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()


def found(items, number, *flags, repo=REPO, links=None):
    code, out, err = run(items, repo, str(number), *flags, links=links)
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

    def test_a_title_naming_several_prs_holds_each(self):
        items = [thread("pair", "◎ #5651 #5679 · a", settled=True), thread("plus", "◎ #5815+#5816 · b")]
        self.assertEqual((found(items, 5679)["threadId"], found(items, 5651)["threadId"]), ("pair", "pair"))
        self.assertEqual(found(items, 5816)["threadId"], "plus")
        self.assertIsNone(found(items, 5680))

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
        self.assertIsNone(found([thread("s", "◎ #62 · a", [pr(62, "stack", repo="octo/skills")])], 62))
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

    def test_none_asks_for_every_hiding_threads_links(self):
        items = [thread(f"big{i}", f"◎ #{i} · a", [pr(i)], open_count=6) for i in range(1, 5)]
        code, out, err = run(items, REPO, "9")
        self.assertEqual((code, out["needLinks"]), (3, ["big1", "big2", "big3", "big4"]), err)

    def test_a_title_or_stack_match_still_asks_while_a_thread_hides_links(self):
        hiding = thread("big", "◎ #1 · a", [pr(1)], open_count=6)
        for match in (thread("t", "Review #9 · b"), thread("s", "◎ #8 · c", [pr(8), pr(9, "stack")])):
            code, out, _ = run([match, hiding], REPO, "9")
            self.assertEqual((code, out["needLinks"]), (3, ["big"]))

    def test_a_thread_linking_the_pr_needs_only_links_that_could_outrank_it(self):
        own = thread("own", "◎ #9 · a", [pr(9)], updated="2026-11-13T10:00:00Z")
        older = thread("older", "◎ #1 · b", [pr(1)], open_count=6, updated="2026-11-01T00:00:00Z")
        settled = thread("settled", "◎ #2 · c", [pr(2)], open_count=6, settled=True, updated="2026-11-20T00:00:00Z")
        self.assertEqual(found([own, older, settled], 9)["threadId"], "own")
        self.assertEqual(found([{**own, "openPullRequestCount": 6}], 9)["threadId"], "own")
        newer = thread("newer", "◎ #3 · d", [pr(3)], open_count=6, updated="2026-11-20T00:00:00Z")
        code, out, _ = run([own, older, newer], REPO, "9")
        self.assertEqual((code, out["needLinks"]), (3, ["newer"]))
        tied = thread("tied", "◎ #4 · e", [pr(4)], open_count=6, updated=own["updatedAt"])
        code, out, _ = run([tied, own], REPO, "9")
        self.assertEqual((code, out["needLinks"]), (3, ["tied"]))
        code, out, _ = run([{**own, "settled": True}, older], REPO, "9")
        self.assertEqual((code, out["needLinks"]), (3, ["older"]))

    def test_full_links_find_a_link_the_list_hid(self):
        # T3 keeps a stack layer's link after GitHub's stack forgets it.
        big = thread("big", "◎ #6093 · a", [pr(n, "stack") for n in range(6100, 6105)], open_count=6)
        full = {"big": listed(*big["pullRequests"], pr(6098, "stack"))}
        held = found([big], 6098, links=full)
        self.assertEqual((held["threadId"], held["match"]), ("big", "stack"))
        self.assertIsNone(found([big, thread("t", "Review #7 · b")], 7000, links=full))
        self.assertEqual(found([thread("t", "Review #7 · b"), big], 7, links=full)["match"], "title")

    def test_a_saved_list_missing_a_link_the_list_shows_fails(self):
        big = thread("big", "◎ #1 · a", [pr(n) for n in (1, 2, 3, 4, 9)], open_count=6)
        code, out, err = run([big], REPO, "9", links={"big": listed(*[pr(n) for n in (1, 2, 3, 4, 5, 6)])})
        self.assertEqual((code, out), (2, None))
        self.assertIn("#9", err)

    def test_a_thread_that_no_longer_hides_links_ignores_its_saved_list(self):
        whole = thread("whole", "◎ #1 · a", [pr(1), pr(2)])
        self.assertIsNone(found([whole], 9, links={"whole": listed(pr(1), pr(2), pr(9))}))

    def test_a_link_of_unknown_state_counts(self):
        big = thread("big", "◎ #1 · a", [pr(1)], open_count=2)
        self.assertEqual(found([big], 9, links={"big": listed(pr(1), {**pr(9), "state": None})})["match"], "linked")

    def test_a_missing_list_fails_even_beside_a_thread_linking_the_pr(self):
        own = thread("own", "◎ #1 · a", [pr(9)], settled=True, open_count=2)
        other = thread("other", "◎ #11 · b", [pr(11)], open_count=2)
        code, out, err = run([own, other], REPO, "9", links={"own": listed(pr(9), pr(1))})
        self.assertEqual((code, out), (2, None))
        self.assertIn("other", err)
        held = found([own, other], 9, links={"own": listed(pr(9), pr(1)), "other": listed(pr(11), pr(9))})
        self.assertEqual(held["threadId"], "other")

    def test_links_must_cover_every_hiding_thread_in_full(self):
        items = [thread("a", "◎ #1 · a", [pr(1)], open_count=2), thread("b", "◎ #2 · b", [pr(2)], open_count=2)]
        whole = listed(pr(1), pr(3))
        for links in ({"a": whole}, {"a": whole, "b": listed(pr(2))},
                      {"a": whole, "b": {**listed(pr(2), pr(4)), "nextCursor": "x"}},
                      {"a": whole, "b": [pr(2), pr(4)]}, [whole],
                      {"a": whole, "b": listed(pr(2), pr(2))},
                      {"a": whole, "b": listed(pr(2), {"repository": REPO, "source": "stack"})},
                      {"a": whole, "b": listed(pr(2), {k: v for k, v in pr(9).items() if k != "source"})},
                      {"a": whole, "b": listed(pr(2), {**pr(9), "watching": "no"})}):
            code, out, err = run(items, REPO, "9", links=links)
            self.assertEqual((code, out), (2, None), links)
            self.assertIn("--links", err)

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

    def test_a_full_page_is_read_twice(self):
        page = [thread(f"t{i}", f"Work {i}") for i in range(99)] + [thread("old", "Review #5 · a", settled=True)]
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

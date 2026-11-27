"""Tests for named_links.unnamed, which scripts/check_examples.py runs on the kit's
example replies and named-links-check.py on posts, and for the modules only the
check uses."""
import json, os, pathlib, re, shutil, tempfile, unittest, unittest.mock

import denied_posts, merge_go, named_links, posted_text, turn_block
from test_hooks import block

NAMED = "[DEV-4024, Close split exports](https://linear.app/acme/issue/DEV-4024)"


def ids(text):
    return [cited.id for cited in named_links.unnamed(text)]


class Unnamed(unittest.TestCase):
    def test_a_bare_linear_id_is_unnamed(self):
        self.assertEqual(named_links.unnamed("Fine.\n\nShould we close DEV-4024?"),
                         [named_links.Cited("DEV-4024", 2)])

    def test_a_named_link_covers_every_later_citation(self):
        self.assertEqual(ids(f"{NAMED} is merged.\n\nSo DEV-4024 can close."), [])

    def test_a_link_without_naming_words_does_not_name(self):
        self.assertEqual(ids("[DEV-4024](https://linear.app/x) and [PR #9](https://github.com/a/b/pull/9)"),
                         ["DEV-4024", "#9"])

    def test_a_one_word_name_and_a_reference_link_name(self):
        self.assertEqual(ids("[#12, Login](https://github.com/acme/app/pull/12) and #12"), [])
        self.assertEqual(ids("[#12, Fix login][pr] and #12\n\n[pr]: https://github.com/acme/app/pull/12"), [])
        self.assertEqual(ids("[See the issue DEV-5](https://linear.app/x)"), ["DEV-5"])

    def test_code_comments_and_the_turn_block_are_not_prose(self):
        reply = ("Run `gh pr merge 124` for `DEV-1`.\n\n```\nDEV-2 #3\n```\n\n````md\n#4\n````\n"
                 "<!-- a note on #5 -->\n" + block({"state": "stop", "needs": [], "options": [
                     {"key": "a", "class": "stop:merge", "text": "merge #124"}]}))
        self.assertEqual(ids(reply), [])

    def test_a_fence_in_a_list_item_and_a_comment_opener_in_code_hide_only_code(self):
        self.assertEqual(ids("- ```text\n  #12\n  ```\n\nFixed #14."), ["#14"])
        self.assertEqual(ids("> ~~~\n> #12\n> ~~~\nand #15"), ["#15"])
        self.assertEqual(ids("See `<!--` and DEV-7. <!-- not shown -->"), ["DEV-7"])

    def test_a_one_character_repo_and_a_number_before_punctuation_are_ids(self):
        self.assertEqual(ids("Merged x#12 and #13; next is #14."), ["x#12", "#13", "#14"])

    def test_a_named_repo_id_covers_its_bare_number_but_not_another_repo(self):
        self.assertEqual(ids("[addystack#12, Fix the gate](u) then #12 and dotfiles#12"), ["dotfiles#12"])
        self.assertEqual(ids("[#12, Fix the gate](u) then dotfiles#12"), ["dotfiles#12"])
        self.assertEqual(ids("[acme/app#7, Fix the gate](u) then app#7 and #7"), [])
        self.assertEqual(ids("[acme/app#7, Fix the gate](u) and other/app#7"), ["other/app#7"])
        self.assertEqual(ids("[app#7, Fix the gate](u) and acme/app#7"), [])

    def test_each_id_once_in_first_cited_order(self):
        self.assertEqual(named_links.unnamed("#2 then\nDEV-1 and #2\nOPS-3, the #5800/#5808 stack"),
                         [named_links.Cited("#2", 0), named_links.Cited("DEV-1", 1),
                          named_links.Cited("OPS-3", 2), named_links.Cited("#5800", 2),
                          named_links.Cited("#5808", 2)])

    def test_standards_colors_languages_entities_and_urls_are_not_ids(self):
        prose = ("UTF-8, SHA-256, GPT-4, ISO-8601, CVE-2024-1234, RFC-9110 and ADR-0001. color:#333; and "
                 "#000 and #fff. C# and F# 10. &#123; ## Heading 2. See https://github.com/a/b/pull/3#issuecomment-12 "
                 "and <https://x.dev/#12>.")
        self.assertEqual(ids(prose), [])

    def test_lines_count_after_crlf_and_a_fence(self):
        self.assertEqual(named_links.unnamed("a\r\n```\nx\n```\r\nsee #7"), [named_links.Cited("#7", 4)])


class MergeGoStillReadsTheOption(unittest.TestCase):
    """The named link goes in the visible reply; the turn block's option keeps `merge #124`,
    so merge-gate's pick still reads as a go for #124."""

    REPLY = ("🟡 **Merge #124, so a retried upload stops creating a second receipt?**\n\n"
             "| PR | State |\n|---|---|\n"
             "| [#124, A retry reuses its receipt](https://github.com/acme/app/pull/124) | draft |\n\n"
             + block({"state": "stop", "needs": [], "options": [
                 {"key": "a", "class": "stop:merge", "text": "merge #124"}]}))

    def test_the_reply_is_clean_and_its_pick_is_a_merge_go(self):
        self.assertEqual(named_links.unnamed(self.REPLY), [])
        option = turn_block.picked(self.REPLY, "a")
        self.assertEqual(option.cls, "stop:merge")
        self.assertTrue(merge_go.literal_go(option.text))
        self.assertTrue(merge_go.names(option.text, 124, "acme", "app", [124]))


class TheTableNamesTheNextLinesId(unittest.TestCase):
    """The Next line repeats `push #105` as its option reads, since push-gate matches a typed
    go against it; naming #105 once in the table covers it."""

    REPLY = ("🟡 **Push the rebased PR?**\n\n"
             "| [#105, Tell agents which ids their last reply left unnamed](https://github.com/acme/app/pull/105) "
             "| ready |\n|---|---|\n\n---\n\n**Next**\n\n- `a` → push #105 (dismisses the reviewer's approval)\n\n"
             + block({"state": "stop", "needs": [], "options": [
                 {"key": "a", "class": "stop:push", "text": "push #105 (dismisses the reviewer's approval)"}]}))

    def test_the_reply_is_clean(self):
        self.assertEqual(named_links.unnamed(self.REPLY), [])


def bash(command):
    return {"command": command}


class PostedText(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def posts(self, tool, tool_input, cwd=None):
        return posted_text.posts(tool, tool_input, self.folder if cwd is None else cwd)

    def test_gh_body_flags_in_each_form(self):
        for command in ('gh pr create --title "Fix #9" --body "see #12"', "gh pr create -t x -b 'see #12'",
                        'gh pr create --body="see #12"', "gh pr new -bsee", 'git push && gh pr create -b "see #12"'):
            with self.subTest(command=command):
                [post] = self.posts("Bash", bash(command))
                self.assertEqual(post.target, "gh pr create" if "new" not in command else "gh pr new")
                self.assertNotIn("#9", post.text)
        self.assertEqual(self.posts("Bash", bash("gh pr comment 12 --body 'Fixed in #14.'")),
                         [posted_text.Post("gh pr comment 12", "Fixed in #14.")])
        self.assertEqual(self.posts("Bash", bash('gh pr edit 12 --body "a \\"quoted\\" #3"')),
                         [posted_text.Post("gh pr edit 12", 'a "quoted" #3')])

    def test_a_heredoc_body_in_a_substitution_or_on_stdin(self):
        command = 'gh pr create --title t --body "$(cat <<\'EOF\'\n## Summary\nCloses #12 "quoted"\nEOF\n)"'
        [post] = self.posts("Bash", bash(command))
        self.assertIn('Closes #12 "quoted"', post.text)
        [post] = self.posts("Bash", bash("gh pr comment 7 --body-file - <<'EOF'\nSee DEV-4.\nEOF"))
        self.assertEqual(post, posted_text.Post("gh pr comment 7", "See DEV-4."))
        self.assertEqual(self.posts("Bash", bash("printf 'see #1' | gh pr comment 7 -F -")), [])

    def test_a_body_file_relative_to_where_the_command_runs(self):
        pathlib.Path(self.folder, "sub").mkdir()
        pathlib.Path(self.folder, "sub", "b.md").write_text("See DEV-4.")
        [post] = self.posts("Bash", bash("cd sub && gh pr create --body-file b.md"))
        self.assertEqual(post.text, "See DEV-4.")
        self.assertEqual(self.posts("Bash", bash("cd $X && gh pr create -F b.md")), [])
        self.assertEqual(self.posts("Bash", bash("gh pr create -F sub/b.md"), cwd=""), [])

    def test_a_file_the_command_writes_reads_its_heredoc_or_passes(self):
        pathlib.Path(self.folder, "b.md").write_text("stale #99")
        command = "cat > b.md <<'EOF'\nFresh DEV-4.\nEOF\ngh pr create --body-file b.md"
        self.assertEqual(self.posts("Bash", bash(command)), [posted_text.Post("gh pr create", "Fresh DEV-4.")])
        self.assertEqual(self.posts("Bash", bash("cat >b.md <<EOF && gh pr create -F b.md\nFresh DEV-4.\nEOF"))[0].text,
                         "Fresh DEV-4.")
        for command in ("echo hi > b.md && gh pr create -F b.md", "cat >> b.md <<EOF\nx\nEOF\ngh pr create -F b.md",
                        "cp a.md b.md; gh pr create -F b.md"):
            with self.subTest(command=command):
                self.assertEqual(self.posts("Bash", bash(command)), [])

    def test_bodies_it_cannot_place_pass(self):
        fifo = os.path.join(self.folder, "fifo")
        os.mkfifo(fifo)
        pathlib.Path(self.folder, "big.md").write_text("#1 " * 200_000)
        for path in (fifo, "/dev/null", "missing.md", "big.md", self.folder):
            with self.subTest(path=path):
                self.assertEqual(self.posts("Bash", bash(f"gh pr create --body-file {path}")), [])

    def test_other_commands_and_titles_post_nothing(self):
        for command in ("gh pr create --title 'Fix #12' --fill", "gh pr edit 3 --title '#4' --add-label x",
                        "echo gh pr create --body '#12'", "gh pr view 12", "git commit -m '#12'"):
            with self.subTest(command=command):
                self.assertEqual(self.posts("Bash", bash(command)), [])

    def test_t3_pull_request_bodies(self):
        self.assertEqual(self.posts("mcp__t3-code__pull_request_create", {"title": "#1", "body": "see #12"}),
                         [posted_text.Post("pull_request_create", "see #12")])
        self.assertEqual(self.posts("mcp__t3-code__pull_request_update", {"number": 5, "body": "DEV-4"}),
                         [posted_text.Post("pull_request_update 5", "DEV-4")])
        self.assertEqual(self.posts("mcp__t3-code__pull_request_update", {"number": 5, "ready": True}), [])

    def test_linear_text_fields_and_patch_inserts(self):
        issue = {"team": "Core", "title": "DEV-1", "relatedTo": ["DEV-2"], "description": "After DEV-3."}
        self.assertEqual(self.posts("mcp__claude_ai_Linear__save_issue", issue),
                         [posted_text.Post("save_issue new Core", "After DEV-3.")])
        patch = {"id": "DEV-9", "patch": [{"op": "insert_after", "anchor": "DEV-5", "text": "See DEV-6."},
                                          {"op": "replace", "old_string": "DEV-7", "new_string": "DEV-8"}]}
        [post] = self.posts("mcp__linear__save_issue", patch)
        self.assertEqual(post.target, "save_issue DEV-9")
        self.assertEqual(ids(post.text), ["DEV-6", "DEV-8"])
        self.assertEqual(self.posts("mcp__claude_ai_Linear__save_comment", {"issueId": "DEV-9", "body": "x"}),
                         [posted_text.Post("save_comment DEV-9", "x")])
        for fields in ({"id": "DEV-9", "relatedTo": ["DEV-4"]}, {"id": "DEV-9", "duplicateOf": "DEV-4", "state": "x"}):
            self.assertEqual(self.posts("mcp__claude_ai_Linear__save_issue", fields), [])

    def test_executor_calls_unwrap_to_linear(self):
        call = lambda path, fields: {"path": path, "input": {"accountId": "acc_1", "input": fields}}
        one = call('tools["linear-mcp"].save_comment', {"issueId": "JOK-1", "body": "See JOK-2."})
        self.assertEqual(self.posts("mcp__executor-personal__call", {"calls": one}),
                         [posted_text.Post("save_comment JOK-1", "See JOK-2.")])
        calls = [call('tools["linear-mcp"].get_issue', {"id": "JOK-1"}),
                 call("tools.linear-mcp.save_issue", {"id": "JOK-1", "description": "JOK-3"})]
        self.assertEqual(self.posts("mcp__executor-work__call", {"calls": calls}),
                         [posted_text.Post("save_issue JOK-1", "JOK-3")])

    def test_unexpected_shapes_post_nothing(self):
        for tool, tool_input in (("Bash", None), ("Bash", {"command": 3}), ("Read", {"command": "gh pr create -b x"}),
                                 ("mcp__executor-x__call", {"calls": "x"}), ("mcp__linear__save_issue", []),
                                 (None, None), ("mcp__t3-code__pull_request_create", {"body": 3})):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assertEqual(posted_text.posts(tool, tool_input, None), [])

    def test_the_matcher_names_exactly_the_routes(self):
        for tool in ("Bash", "mcp__t3-code__pull_request_create", "mcp__t3-code__pull_request_update",
                     "mcp__claude_ai_Linear__save_project", "mcp__linear__save_comment", "mcp__executor-work__call"):
            self.assertTrue(re.fullmatch(posted_text.MATCHER, tool), tool)
        for tool in ("Read", "mcp__t3-code__pull_request_merge", "mcp__linear__get_issue", "mcp__executor-x__execute"):
            self.assertFalse(re.fullmatch(posted_text.MATCHER, tool), tool)


class DeniedPosts(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        patcher = unittest.mock.patch.dict(os.environ, {"ADDYSTACK_STATE": self.folder})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_repeat_passes_and_another_session_or_target_is_new(self):
        self.assertTrue(denied_posts.first("s1", "gh pr create", "see #12"))
        self.assertFalse(denied_posts.first("s1", "gh pr create", "see #12"))
        self.assertTrue(denied_posts.first("s2", "gh pr create", "see #12"))
        self.assertTrue(denied_posts.first("s1", "gh pr comment 3", "see #12"))
        self.assertTrue(denied_posts.first("s1", "gh pr create", "see #13"))
        record = pathlib.Path(self.folder, "named-links-denied.json").read_text()
        self.assertNotIn("#12", record)

    def test_the_record_keeps_the_newest_200(self):
        for number in range(205):
            denied_posts.first("s", "t", str(number))
        self.assertEqual(len(json.loads(pathlib.Path(self.folder, "named-links-denied.json").read_text())), 200)
        self.assertFalse(denied_posts.first("s", "t", "204"))
        self.assertTrue(denied_posts.first("s", "t", "0"))

    def test_no_session_or_an_unusable_record_passes(self):
        self.assertFalse(denied_posts.first(None, "t", "x"))
        self.assertFalse(denied_posts.first("", "t", "x"))
        pathlib.Path(self.folder, "named-links-denied.json").write_text("not json")
        self.assertFalse(denied_posts.first("s", "t", "x"))
        os.environ["ADDYSTACK_STATE"] = os.path.join(self.folder, "named-links-denied.json", "under-a-file")
        self.assertFalse(denied_posts.first("s", "t", "y"))


if __name__ == "__main__":
    unittest.main()

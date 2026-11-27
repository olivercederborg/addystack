"""Tests for named_links.unnamed, which scripts/check_examples.py runs on the kit's
example replies and named-links-check.py on posts, and for the modules only the
check uses."""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile, unittest, unittest.mock

import denied_posts, merge_go, named_links, posted_text, turn_block
from test_hooks import HOOKS, block

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
        for dash in ("-", "'-'", '"-"'):
            with self.subTest(dash=dash):
                [post] = self.posts("Bash", bash(f"gh pr comment 7 --body-file {dash} <<'EOF'\nSee DEV-4.\nEOF"))
                self.assertEqual(post, posted_text.Post("gh pr comment 7", "See DEV-4."))
        self.assertEqual(self.posts("Bash", bash("printf 'see #1' | gh pr comment 7 -F -")), [])

    def test_text_the_shell_expands_passes(self):
        for command in ('gh pr comment 1 --body "see #12 $LINK"', "gh pr comment 1 -b see#12$X",
                        'if x; then LINK=y; fi; gh pr comment 1 --body "see #12 $LINK"',
                        'gh pr comment 1 -b "see #12 `date`"', "gh pr comment 1 -F - <<EOF\nsee #12 $LINK\nEOF",
                        'gh pr create --body "$(cat <<EOF\nsee #12 $LINK\nEOF\n)"',
                        "cat > b.md <<EOF\nsee #12 $LINK\nEOF\ngh pr create -F b.md",
                        'gh pr create -b "see #12 \\\\$LINK"'):
            with self.subTest(command=command):
                self.assertEqual(self.posts("Bash", bash(command)), [])
        for command in ("gh pr comment 1 -b 'costs $5, see #12'", 'gh pr comment 1 -b "costs \\$5, see #12"',
                        "gh pr comment 1 -F - <<'EOF'\ncosts $5, see #12\nEOF"):
            with self.subTest(command=command):
                [post] = self.posts("Bash", bash(command))
                self.assertIn("$5, see #12", post.text)

    def test_a_body_file_through_a_variable_the_command_sets(self):
        pathlib.Path(self.folder, "b.md").write_text("See DEV-4.")
        folder = self.folder
        for command in (f"S={folder} && gh pr edit 5 --body-file $S/b.md", f'S="{folder}"; B="$S/b.md"; gh pr edit 5 -F "$B"',
                        f"export S={folder}\ngh pr edit 5 --body-file ${{S}}/b.md"):
            with self.subTest(command=command):
                self.assertEqual(self.posts("Bash", bash(command)), [posted_text.Post("gh pr edit 5", "See DEV-4.")])
        command = f"S={folder} && cat > $S/new.md <<'EOF'\nFresh DEV-5.\nEOF\ngh pr create --body-file $S/new.md"
        self.assertEqual(self.posts("Bash", bash(command)), [posted_text.Post("gh pr create", "Fresh DEV-5.")])
        self.assertEqual(self.posts("Bash", bash('B="see DEV-6"; gh pr comment 1 -b "$B"'))[0].text, "see DEV-6")
        self.assertEqual(self.posts("Bash", bash(f"cd {folder} && S={folder}\ngh pr edit 5 -F $S/b.md"))[0].text, "See DEV-4.")
        for command in ("B='see #13'; read -r B <<<'see #12'; gh pr comment 1 -b \"$B\"",
                        "B='see #13'; for B in x; do :; done; gh pr comment 1 -b \"$B\"",
                        "B='see #13'; eval \"$X\"; gh pr comment 1 -b \"$B\"",
                        "gh pr edit 5 -F $UNSET/b.md", f"if x; then S={folder}; fi; gh pr edit 5 -F $S/b.md",
                        f"true || S={folder}; gh pr edit 5 -F $S/b.md", "S=$(pwd); gh pr edit 5 -F $S/b.md"):
            with self.subTest(command=command):
                self.assertEqual(self.posts("Bash", bash(command)), [])

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
        self.assertEqual(self.posts("Bash", bash("gh pr create -F b.md && rm b.md"))[0].text, "stale #99")
        self.assertEqual(self.posts("Bash", bash(command + " && rm b.md"))[0].text, "Fresh DEV-4.")
        for check in ("node ~/.agents/skills/open-pr/scripts/check-body.mjs b.md", "wc -c b.md", "grep -n DEV b.md"):
            with self.subTest(check=check):
                written = "cat > b.md <<'EOF'\nFresh DEV-4.\nEOF\n"
                self.assertEqual(self.posts("Bash", bash(f"{written}{check} && gh pr create -F b.md")),
                                 [posted_text.Post("gh pr create", "Fresh DEV-4.")])
                self.assertEqual(self.posts("Bash", bash(f"{check} && gh pr create -F b.md")),
                                 [posted_text.Post("gh pr create", "stale #99")])
        self.assertEqual(self.posts("Bash", bash("cat b.md > c.md && gh pr create -F b.md"))[0].text, "stale #99")
        for command in ("echo hi > b.md && gh pr create -F b.md", "cat >> b.md <<EOF\nx\nEOF\ngh pr create -F b.md",
                        "sed -i '' s/x/y/ b.md && gh pr create -F b.md", "grep x a.md > b.md; gh pr create -F b.md",
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

    def test_the_target_names_the_destination(self):
        self.assertEqual([post.target for n in (1, 2)
                          for post in self.posts("Bash", bash(f"gh pr comment --attach shot.png {n} -b 'see #12'"))],
                         ["gh pr comment 1", "gh pr comment 2"])
        self.assertEqual([post.target for command in ("gh pr comment 23 -R acme/one -b 'see #12'",
                                                       "gh pr comment 23 --repo acme/two -b 'see #12'")
                          for post in self.posts("Bash", bash(command))],
                         ["gh pr comment 23 acme/one", "gh pr comment 23 acme/two"])
        self.assertEqual([post.target for repo in ("acme/one", "acme/two")
                          for post in self.posts("Bash", bash(f"R={repo}; N=23; gh pr comment $N --repo \"$R\" -b 'see #12'"))],
                         ["gh pr comment 23 acme/one", "gh pr comment 23 acme/two"])
        self.assertEqual(self.posts("Bash", bash("gh pr comment $N -b 'see #12'")), [])
        [post] = self.posts("Bash", bash("FILE=-; gh pr comment 1 -F \"$FILE\" <<'EOF'\nsee #12\nEOF"))
        self.assertEqual(post.text, "see #12")
        self.assertEqual([post.target for project in ("P-1", "P-2")
                          for post in self.posts("mcp__linear__save_comment", {"projectId": project, "body": "DEV-12"})],
                         ["save_comment P-1", "save_comment P-2"])

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


class NamedLinksCheck(unittest.TestCase):
    """Plan checks 1-6, through the hook's stdin."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def check(self, tool, tool_input, session_id="s", state=None):
        out = subprocess.run([str(HOOKS / "named-links-check.py")], capture_output=True, text=True, check=True,
                             input=json.dumps({"hook_event_name": "PreToolUse", "session_id": session_id,
                                               "cwd": self.folder, "tool_name": tool, "tool_input": tool_input}),
                             env={**os.environ, "ADDYSTACK_STATE": state or os.path.join(self.folder, "state")})
        if not out.stdout:
            return None
        output = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual((output["hookEventName"], output["permissionDecision"]), ("PreToolUse", "deny"))
        return output["permissionDecisionReason"]

    def test_an_unnamed_id_is_denied_and_a_named_one_passes(self):
        denied = self.check("Bash", bash('gh pr create --title "Fix #9" --body "see #12"'))
        self.assertIn("gh pr create: #12", denied)
        self.assertNotIn("#9", denied)
        self.assertIn("Closes #12", denied)
        self.assertIsNone(self.check("Bash", bash(
            "gh pr create --body '[#12, Fix exports](https://github.com/a/b/pull/12)'")))

    def test_the_heredoc_written_body_file_is_read_not_the_stale_file(self):
        pathlib.Path(self.folder, "b.md").write_text(f"{NAMED}")
        denied = self.check("Bash", bash("cat > b.md <<'EOF'\nFixes DEV-4.\nEOF\ngh pr create --body-file b.md"))
        self.assertIn("DEV-4", denied)

    def test_an_identical_retry_passes_and_another_session_is_denied(self):
        command = bash("gh pr comment 3 --body 'see #12'")
        self.assertIsNotNone(self.check("Bash", command))
        self.assertIsNone(self.check("Bash", command))
        self.assertIsNotNone(self.check("Bash", command, session_id="other"))
        self.assertIsNotNone(self.check("Bash", bash("gh pr comment 4 --body 'see #12'")))

    def test_linear_through_direct_mcp_and_executor(self):
        self.assertIn("save_issue new Core: DEV-4", self.check(
            "mcp__claude_ai_Linear__save_issue", {"team": "Core", "title": "t", "description": "After DEV-4."}))
        call = {"path": 'tools["linear-mcp"].save_issue',
                "input": {"accountId": "acc_1", "input": {"id": "DEV-9", "description": "After DEV-4."}}}
        self.assertIn("save_issue DEV-9: DEV-4", self.check("mcp__executor-work__call", {"calls": [call]}))
        patch = {"id": "DEV-9", "patch": [{"op": "insert_after", "anchor": "x", "text": "See DEV-5."}]}
        self.assertIn("DEV-5", self.check("mcp__linear__save_issue", patch))
        self.assertIsNone(self.check("mcp__claude_ai_Linear__save_issue", {"id": "DEV-9", "relatedTo": ["DEV-4"]}))

    def test_a_t3_pull_request_body(self):
        self.assertIn("#12", self.check("mcp__t3-code__pull_request_create", {"title": "t", "body": "see #12"}))

    def test_a_fifo_or_missing_body_file_and_bad_input_pass(self):
        fifo = os.path.join(self.folder, "fifo")
        os.mkfifo(fifo)
        self.assertIsNone(self.check("Bash", bash(f"gh pr create --body-file {fifo}")))
        self.assertIsNone(self.check("Bash", bash("gh pr create --body-file missing.md")))
        for payload in ("", "null", "{}", '{"tool_name": "Bash", "tool_input": {"command": 3}}'):
            with self.subTest(payload=payload):
                out = subprocess.run([str(HOOKS / "named-links-check.py")], input=payload, capture_output=True,
                                     text=True)
                self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_an_unwritable_record_lets_the_post_through(self):
        blocker = pathlib.Path(self.folder, "file")
        blocker.write_text("")
        self.assertIsNone(self.check("Bash", bash("gh pr create -b 'see #12'"), state=str(blocker / "state")))


class NamedLinksCheckInstall(unittest.TestCase):
    def test_each_runtimes_entry_carries_the_route_matcher(self):
        manifest = json.loads((HOOKS / "manifest.json").read_text())
        for runtime in ("claude", "codex"):
            [entry] = [entry for entry in manifest[runtime] if entry["id"] == "named-links-check"]
            self.assertEqual(entry["matcher"], posted_text.MATCHER, runtime)

    def test_only_reply_shape_installs_it(self):
        if str(HOOKS.parent / "lib") not in sys.path:
            sys.path.append(str(HOOKS.parent / "lib"))
        import config, hookset
        with tempfile.TemporaryDirectory() as folder:
            user = pathlib.Path(folder, "addystack.jsonc")
            for replies, on in (({"style": "reply-shape"}, True), ({}, False)):
                user.write_text(json.dumps({"hooks": {"preset": "all"}, "replies": replies}))
                for runtime in ("claude", "codex"):
                    with self.subTest(replies=replies, runtime=runtime):
                        selected = [entry.id for entry in hookset.select(config.resolve(user), runtime, "linux")]
                        self.assertEqual("named-links-check" in selected, on)


if __name__ == "__main__":
    unittest.main()

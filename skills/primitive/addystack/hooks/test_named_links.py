"""Tests for named_links.unnamed, transcripts.final_reply, and named-links-notice.py, which
pipes the UserPromptSubmit event to them. Transcript tails follow the real ones: Claude
Code 2.1.326 writes one entry per content part, each with the message's id and stop
reason, then attachment, system, last-prompt, and queue-operation entries, and logs the
next prompt only as a queue-operation before the hook runs; Codex 0.169 writes its final
answer, then token counts and task_complete."""
import json, os, pathlib, subprocess, tempfile, unittest

import merge_go, named_links, transcripts, turn_block
from test_hooks import HOOKS, block, claude_said, codex_said, codex_wrote, state_db

HOOK = "named-links-notice.py"
NAMED = "[DEV-4024, Close split exports](https://linear.app/acme/issue/DEV-4024)"


def ids(text):
    return [cited.id for cited in named_links.unnamed(text)]


def claude_reply(text, message_id="msg_1"):
    """A Claude Code end_turn message as it lands: a thinking part, then the text part."""
    message = {"id": message_id, "role": "assistant", "stop_reason": "end_turn"}
    return [{"type": "assistant", "isSidechain": False, "message": {**message, "content": [
                {"type": "thinking", "thinking": "…"}]}},
            {"type": "assistant", "isSidechain": False, "message": {**message, "content": [
                {"type": "text", "text": text}]}}]


# What Claude Code writes after the reply, and the queued next prompt, before the hook runs.
CLAUDE_AFTER = [{"type": "attachment", "attachment": {}},
                {"type": "system", "subtype": "stop_hook_summary"},
                {"type": "last-prompt", "lastPrompt": "say ok"},
                {"type": "queue-operation", "operation": "enqueue", "content": "next prompt"},
                {"type": "queue-operation", "operation": "dequeue"}]
CODEX_AFTER = [{"type": "token_usage_record"},
               {"type": "event_msg", "payload": {"type": "token_count"}},
               {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "…"}}]


def claude_transcript(reply):
    return [claude_said("Should we close it?"), *claude_reply(reply), *CLAUDE_AFTER]


def codex_transcript(reply, commentary="Looking."):
    return [codex_said("Should we close it?"), codex_wrote(commentary, phase="commentary"),
            codex_wrote(reply), *CODEX_AFTER]


class Unnamed(unittest.TestCase):
    def test_a_bare_linear_id_is_unnamed(self):
        self.assertEqual(named_links.unnamed("Fine.\n\nShould we close DEV-4024?"),
                         [named_links.Cited("DEV-4024", 2)])

    def test_a_named_link_covers_every_later_citation(self):
        self.assertEqual(ids(f"{NAMED} is merged.\n\nSo DEV-4024 can close."), [])

    def test_a_link_without_naming_words_does_not_name(self):
        self.assertEqual(ids("[DEV-4024](https://linear.app/x) and [PR #9](https://github.com/a/b/pull/9)"),
                         ["DEV-4024", "#9"])

    def test_code_comments_and_the_turn_block_are_not_prose(self):
        reply = ("Run `gh pr merge 124` for `DEV-1`.\n\n```\nDEV-2 #3\n```\n\n````md\n#4\n````\n"
                 "<!-- a note on #5 -->\n" + block({"state": "stop", "needs": [], "options": [
                     {"key": "a", "class": "stop:merge", "text": "merge #124"}]}))
        self.assertEqual(ids(reply), [])

    def test_a_named_repo_id_covers_its_bare_number_but_not_another_repo(self):
        self.assertEqual(ids("[addystack#12, Fix the gate](u) then #12 and dotfiles#12"), ["dotfiles#12"])
        self.assertEqual(ids("[#12, Fix the gate](u) then dotfiles#12"), ["dotfiles#12"])
        self.assertEqual(ids("[acme/app#7, Fix the gate](u) then app#7 and #7"), [])

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


class FinalReply(unittest.TestCase):
    def final(self, entries, raw_tail=""):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as transcript:
            transcript.write("".join(json.dumps(entry) + "\n" for entry in entries) + raw_tail)
        self.addCleanup(os.unlink, transcript.name)
        return transcripts.final_reply(transcript.name)

    def test_claude_joins_the_end_turn_messages_text_parts(self):
        first, second = claude_reply("Part one.")[1], claude_reply("Part two.")[1]
        self.assertEqual(self.final([claude_said("go"), first, {"type": "attachment"}, second, *CLAUDE_AFTER]),
                         "Part one.\nPart two.")

    def test_claude_takes_the_last_end_turn_message_only(self):
        entries = [*claude_transcript("Old reply."), claude_said("again"), *claude_reply("New reply.", "msg_2")]
        self.assertEqual(self.final(entries), "New reply.")

    def test_claude_thinking_only_or_sidechain_has_no_reply(self):
        thinking = claude_reply("x")[0]
        self.assertIsNone(self.final([*claude_transcript("Old."), claude_said("again"),
                                      {**thinking, "message": {**thinking["message"], "id": "msg_2"}}]))
        sidechain = {**claude_reply("Side.", "msg_3")[1], "isSidechain": True}
        self.assertEqual(self.final([*claude_transcript("Main."), sidechain]), "Main.")

    def test_codex_takes_the_final_answer_not_the_commentary(self):
        self.assertEqual(self.final(codex_transcript("Done.", commentary="Checking DEV-1.")), "Done.")
        self.assertIsNone(self.final([codex_said("go"), codex_wrote("Checking.", phase="commentary")]))

    def test_an_interrupted_turn_has_no_final_reply(self):
        interrupted = [claude_said("next task"), {"type": "user", "message": {
            "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}]
        self.assertIsNone(self.final([*claude_transcript("Old DEV-1."), *interrupted]))
        self.assertIsNone(self.final([*codex_transcript("Old DEV-1."), codex_said("next task")]))

    def test_an_injected_prompt_after_the_answer_is_not_a_newer_prompt(self):
        agents = codex_said("# AGENTS.md instructions for /repo\n\n<INSTRUCTIONS>…</INSTRUCTIONS>")
        self.assertEqual(self.final([*codex_transcript("Done."), agents]), "Done.")

    def test_a_cut_or_unparsable_last_line_and_a_missing_file(self):
        self.assertEqual(self.final(claude_transcript("Done."), raw_tail='{"type": "assist'), "Done.")
        self.assertIsNone(transcripts.final_reply("/nonexistent/transcript.jsonl"))

    def test_a_reply_far_from_the_end_is_read_across_blocks_and_one_past_the_limit_is_not(self):
        filler = {"type": "progress", "data": "x" * 1000}
        near = (transcripts.TAIL_BLOCK * 3) // 1000
        self.assertEqual(self.final([*claude_transcript("Done."), *[filler] * near]), "Done.")
        past = transcripts.TAIL_LIMIT // 1000 + 10
        self.assertIsNone(self.final([*claude_transcript("Done."), *[filler] * past]))


class NamedLinksNotice(unittest.TestCase):
    def run_hook(self, entries, session_id="s", db="/nonexistent/statev2.sqlite"):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder, "transcript.jsonl")
            path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
            out = subprocess.run([str(HOOKS / HOOK)], capture_output=True, text=True, check=True,
                                 input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session_id,
                                                   "transcript_path": str(path), "prompt": "next"}),
                                 env={**os.environ, "T3_STATE_DB": db})
        return json.loads(out.stdout)["hookSpecificOutput"] if out.stdout else None

    def test_an_unnamed_id_gets_a_notice_naming_it(self):
        for entries in (claude_transcript("Should we close DEV-4024?"), codex_transcript("Should we close DEV-4024?")):
            with self.subTest(entries[-1]["type"]):
                out = self.run_hook(entries)
                self.assertEqual(out["hookEventName"], "UserPromptSubmit")
                self.assertIn("DEV-4024", out["additionalContext"])
                self.assertIn("merge #124", out["additionalContext"])

    def test_a_named_id_cited_bare_later_gets_nothing(self):
        self.assertIsNone(self.run_hook(claude_transcript(f"{NAMED} is merged.\n\nSo DEV-4024 can close.")))

    def test_ids_only_in_code_or_the_turn_block_get_nothing(self):
        reply = "Merged in `DEV-4024`.\n\n```\n#124\n```\n\n" + block({"state": "stop", "needs": [], "options": [
            {"key": "a", "class": "stop:merge", "text": "merge #124"}]})
        self.assertIsNone(self.run_hook(claude_transcript(reply)))

    def test_codex_commentary_and_an_interrupted_turn_get_nothing(self):
        self.assertIsNone(self.run_hook(codex_transcript("Done.", commentary="Checking DEV-4024.")))
        self.assertIsNone(self.run_hook([*codex_transcript("Close DEV-4024?"), codex_said("stop, do X")]))

    def test_a_named_repo_id_flags_another_repos_number(self):
        out = self.run_hook(claude_transcript("[addystack#12, Fix the gate](u) and dotfiles#12."))
        self.assertIn("dotfiles#12", out["additionalContext"])
        self.assertNotIn("addystack#12", out["additionalContext"])

    def test_a_delegated_child_gets_nothing_unless_its_brief_opts_in(self):
        child = "thread:delegated-task:command%3Amcp%3Aabc%3Adelegate-task%3Areview"
        entries = claude_transcript("Should we close DEV-4024?")
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(self.run_hook(entries, db=state_db(folder, child, "Review the PR.")))
            self.assertIsNotNone(self.run_hook(entries, db=state_db(folder, child, "Reply rules: on\nReview it.")))
            self.assertIsNotNone(self.run_hook(entries, db=state_db(folder, "thread:main", "Review the PR.")))

    def test_bad_input_gets_nothing(self):
        for payload in ("", "null", "{}", '{"transcript_path": 3}'):
            with self.subTest(payload=payload):
                out = subprocess.run([str(HOOKS / HOOK)], input=payload, capture_output=True, text=True)
                self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_only_an_unnamed_id_opens_t3s_database_and_none_reads_resolved_json(self):
        # Runs the hook with sqlite3.connect replaced by one that exits, and reports
        # whether resolved.py was imported.
        runner = ("import json, runpy, sqlite3, sys\n"
                  "def opened(*args, **kwargs): print('OPENED'); raise SystemExit\n"
                  "sqlite3.connect = opened\n"
                  "runpy.run_path(sys.argv[1], run_name='__main__')\n"
                  "print('RESOLVED' if 'resolved' in sys.modules else 'NO-RESOLVED')\n")
        for reply, opens in (("All clean.", False), (f"{NAMED} is merged.", False), ("Close DEV-4024?", True)):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as folder:
                path = pathlib.Path(folder, "transcript.jsonl")
                path.write_text("".join(json.dumps(entry) + "\n" for entry in claude_transcript(reply)))
                out = subprocess.run(["python3", "-c", runner, str(HOOKS / HOOK)], capture_output=True, text=True,
                                     input=json.dumps({"session_id": "s", "transcript_path": str(path)})).stdout
                self.assertEqual("OPENED" in out, opens)
                if not opens:
                    self.assertTrue(out.endswith("NO-RESOLVED\n"), out)


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


if __name__ == "__main__":
    unittest.main()

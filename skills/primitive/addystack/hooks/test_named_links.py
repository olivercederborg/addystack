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

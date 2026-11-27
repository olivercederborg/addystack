"""Tests for named_links.unnamed, which scripts/check_examples.py runs on the kit's
example replies."""
import unittest

import merge_go, named_links, turn_block
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


if __name__ == "__main__":
    unittest.main()

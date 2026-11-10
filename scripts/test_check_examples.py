import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import check_examples  # noqa: E402

GOOD = """# Skill

````markdown
✅ **Done.**

**Needs you**

- **Review**: the draft below.

<details><summary>Checks: ✅ 2 passed</summary>

✅ tests · ✅ idioms (grounding)

</details>

---

**Next**

- **`a` → publish** · *recommended*
````
"""


def problems(text):
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder, "SKILL.md")
        path.write_text(text)
        return [message for _, message in check_examples.check(path)]


class CheckExamplesTest(unittest.TestCase):
    def test_current_shape_passes(self):
        self.assertEqual(problems(GOOD), [])

    def test_bold_label_sentence_fails(self):
        bad = GOOD.replace("- **Review**: the draft below.", "**Review** the draft below.")
        self.assertIn("list item", problems(bad)[0])

    def test_bare_details_summary_fails(self):
        bad = GOOD.replace("Checks: ✅ 2 passed", "Details")
        self.assertIn("name what's inside", problems(bad)[0])

    def test_next_without_closing_rule_fails(self):
        bad = GOOD.replace("---\n\n**Next**", "**Next**")
        self.assertIn("closing rule", problems(bad)[0])

    def test_rule_under_text_fails(self):
        bad = GOOD.replace("</details>\n\n---", "</details>\ntext\n---")
        self.assertTrue(any("heading" in message for message in problems(bad)))

    def test_bare_idioms_check_fails(self):
        bad = GOOD.replace("✅ idioms (grounding)", "✅ idioms")
        self.assertIn("name its lenses", problems(bad)[0])

    def test_bare_number_in_next_fails(self):
        bad = GOOD.replace("`a` → publish", "`a` → keep item 48 and publish")
        self.assertIn("'item 48' needs its short name", problems(bad)[0])
        named = GOOD.replace("`a` → publish", "`a` → keep 48 (optional email variables) and publish")
        self.assertEqual(problems(named), [])

    def test_a_next_fragment_needs_no_closing_rule(self):
        self.assertEqual(problems("````markdown\n**Next**\n\n- **`a` → publish** · *recommended*\n````\n"), [])

    def test_rules_outside_examples_are_ignored(self):
        self.assertEqual(problems("**Review** the rule text.\n\n**Next**\n"), [])

    def test_code_inside_an_example_is_ignored(self):
        code = GOOD.replace("✅ tests · ✅ idioms (grounding)", "```text\n**Review** inside code\n```")
        self.assertEqual(problems(code), [])

    def test_a_third_next_option_fails(self):
        two = GOOD.replace("*recommended*\n````", "*recommended*\n- `b` → no: hold it\n````")
        self.assertEqual(problems(two), [])
        three = two.replace("hold it\n````", "hold it\n- `c` → publish a draft\n````")
        self.assertEqual(problems(three), ["Next offers a third option; replies.md allows `a` and `b`"])
        bold = two.replace("hold it\n````", "hold it\n- **`c` → publish a draft** · *recommended*\n````")
        self.assertEqual(problems(bold), ["Next offers a third option; replies.md allows `a` and `b`"])

    def test_a_turn_block_in_an_example_must_parse(self):
        turn = '<!-- turn {"state":"stop","needs":[],"options":[{"key":"a","class":"routine","text":"publish"}]} -->'
        with_block = GOOD.replace("*recommended*\n````", f"*recommended*\n\n{turn}\n````")
        self.assertEqual(problems(with_block), [])
        broken = with_block.replace('"routine"', '"chore"')
        self.assertEqual(problems(broken), ['turn block: options[0].class "chore" is not one of routine, decision, '
                                            'stop:merge, stop:push, stop:post, stop:prod, stop:credential'])
        lines = broken.split("\n")  # the example's inside starts on line 4
        [(number, _)] = check_examples.check_block(4, lines[3:-2])
        self.assertTrue(lines[number - 1].startswith("<!-- turn "))  # it reports the block's line
        trailing = with_block.replace(f"{turn}\n````", f"{turn}\n\nOne more line.\n````")
        self.assertEqual(problems(trailing), ["turn block: the turn block is not the last thing in the reply"])
        # Shown in code, or mentioned in a code span, it's an example of the format, not a block.
        shown = GOOD.replace("✅ tests · ✅ idioms (grounding)", f"```text\n{turn.replace('routine', 'chore')}\n```")
        self.assertEqual(problems(shown), [])
        self.assertEqual(problems(GOOD.replace("the draft below.", "the `<!-- turn ` line.")), [])

    def test_a_bare_number_names_the_need_the_block_gives_it(self):
        turn = ('<!-- turn {"state":"stop","needs":[{"id":3,"kind":"decide","name":"currency column"}],'
                '"options":[{"key":"a","class":"routine","text":"fix 3"}]} -->')
        bad = GOOD.replace("`a` → publish", "`a` → fix 3").replace("*recommended*\n````", f"*recommended*\n\n{turn}\n````")
        self.assertEqual(problems(bad), ["'fix 3' (3 → currency column) needs its short name beside it, "
                                         "as in \"48 (optional email variables)\""])
        # A standing item's id is named the same way.
        standing = turn.replace('"needs":[', '"needs":[],"standing":[')
        self.assertEqual(problems(bad.replace(turn, standing)), ["'fix 3' (3 → currency column) needs its short name "
                                                                 "beside it, as in \"48 (optional email variables)\""])

    def test_a_long_reply_passes(self):
        # Length is the moment's call, not a count (R107).
        filler = " ".join(["word"] * 300)
        self.assertEqual(problems(GOOD.replace("- **Review**: the draft below.", f"- **Review**: the draft below. {filler}")), [])

    def test_a_merge_option_must_be_the_plain_request(self):
        turn = ('<!-- turn {{"state":"stop","needs":[],"options":[{{"key":"a","class":"stop:merge","text":"{text}"}}]}} -->')
        card = GOOD.replace("`a` → publish", "`a` → {text}").replace("*recommended*\n````", "*recommended*\n\n" + turn + "\n````")
        self.assertEqual(problems(card.format(text="merge #12 and #13")), [])
        self.assertEqual(problems(card.format(text="merge #12, then deploy")),
                         ["merge option `a` isn't the plain request merge-gate takes as a go"])

    def test_every_you_accept_example_fills_a_column_per_pr(self):
        # Agents copy examples before rules, so each You accept view shows every PR's cells.
        views = (pathlib.Path(__file__).resolve().parent.parent / "skills/optional/reply-shape/references/views.md").read_text()
        section = views[views.index("## You accept"):views.index("## Comparison")]
        examples = [block for _, block in check_examples.example_blocks(section.splitlines())]
        self.assertTrue(examples)
        cells = check_examples.bare_references.cells
        for block in examples:
            with self.subTest(example=block[0]):
                at = next(n for n, line in enumerate(block) if line.startswith("| You accept |"))
                prs = len(cells(block[at])) - 1
                rows = [line for line in block[at + 2:] if line.startswith("|")]
                self.assertTrue(rows)
                for line in rows:
                    values = [cell.strip() for cell in cells(line)[1:]]
                    self.assertTrue(len(values) == prs and all(values), line)

    def test_every_skill_passes(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for skill in [*sorted(root.glob("skills/*/*/SKILL.md")), *[p for p in [root / "replies.md"] if p.is_file()],
                      *sorted(root.glob("skills/optional/reply-shape/references/*.md"))]:
            with self.subTest(skill=skill.parent.name):
                self.assertEqual(check_examples.check(skill), [])


if __name__ == "__main__":
    unittest.main()

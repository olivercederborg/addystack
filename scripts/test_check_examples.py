import pathlib
import re
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


def table_cells(line):
    """A Markdown table row's cells, split on pipes no backslash escapes."""
    return re.split(r"(?<!\\)\|", line.strip().strip("|"))


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

    def test_an_id_needs_a_link_that_names_it(self):
        unnamed = GOOD.replace("the draft below.", "the draft below.\n\nIt closes DEV-12 and #7.")
        self.assertEqual(problems(unnamed), [
            "cites DEV-12 without a link that names it, as in `[DEV-12, title](url)`",
            "cites #7 without a link that names it, as in `[#7, title](url)`"])
        lines = unnamed.split("\n")  # the example's inside starts on line 4
        [(number, _), _] = check_examples.check_block(4, lines[3:-2])
        self.assertIn("DEV-12", lines[number - 1])  # it reports the citing line
        named = unnamed.replace("DEV-12 and #7", "[DEV-12, Fix exports](https://linear.app/x) and "
                                                 "[#7, Retry the upload](https://github.com/x/y/pull/7), then #7")
        self.assertEqual(problems(named), [])
        self.assertEqual(problems(GOOD.replace("the draft below.", "the `#7` draft below.")), [])

    def test_every_ship_gate_example_shows_what_the_reader_accepts(self):
        # Agents copy examples before rules, so each ship gate in views shows the You accept view.
        views = (pathlib.Path(__file__).resolve().parent.parent / "skills/optional/reply-shape/references/views.md").read_text()
        gate = views[views.index("## Ship gate"):views.index("## Choosing between shapes")]
        examples = [block for _, block in check_examples.example_blocks(gate.splitlines())]
        self.assertEqual(len(examples), 2)
        kinds = ["New", "Changes", "Edits", "Goes live", "Left out"]
        for block in examples:
            with self.subTest(example=block[0]):
                at = next(n for n, line in enumerate(block) if line.startswith("| You accept |"))
                prs = len(table_cells(block[at])) - 1
                rows = {cells[0].strip(): [cell.strip() for cell in cells[1:]]
                        for line in block[at + 2:at + 2 + len(kinds)]
                        for cells in [table_cells(line)]}
                self.assertEqual(list(rows), kinds)  # every kind, in order
                self.assertTrue(all(len(values) == prs and all(values) for values in rows.values()), rows)

    def test_every_skill_passes(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for skill in [*sorted(root.glob("skills/*/*/SKILL.md")), *[p for p in [root / "replies.md"] if p.is_file()],
                      *sorted(root.glob("skills/optional/reply-shape/references/*.md"))]:
            with self.subTest(skill=skill.parent.name):
                self.assertEqual(check_examples.check(skill), [])


if __name__ == "__main__":
    unittest.main()

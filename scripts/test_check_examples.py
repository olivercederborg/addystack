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

    def test_a_long_glance_fails(self):
        filler = " ".join(["word"] * 60)
        bad = GOOD.replace("- **Review**: the draft below.", f"- **Review**: the draft below. {filler}")
        self.assertIn("under 60", problems(bad)[0])
        unmarked = bad.replace("✅ **Done.**", "**Done.**")
        self.assertEqual(problems(unmarked), [])

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

    def test_a_decision_card_pick_needs_a_source(self):
        turn = ('<!-- turn {"state":"stop","needs":[{"id":1,"kind":"decide","name":"publish it"}],'
                '"options":[{"key":"a","class":"decision","text":"publish"}]} -->')
        card = GOOD.replace("**Needs you**", "**Pick**: publish it.\n\n**Needs you**").replace(
            "*recommended*\n````", "*recommended*\n\n" + turn + "\n````")
        self.assertEqual(problems(card), ["the decision card's Pick cites no source; add a **Source** line"])
        self.assertEqual(problems(card.replace("publish it.", "publish it.\n\n**Source**: the launch doc")), [])

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

    def test_every_skill_passes(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for skill in [*sorted(root.glob("skills/*/*/SKILL.md")), *[p for p in [root / "replies.md"] if p.is_file()],
                      *sorted(root.glob("skills/optional/reply-shape/references/*.md"))]:
            with self.subTest(skill=skill.parent.name):
                self.assertEqual(check_examples.check(skill), [])


if __name__ == "__main__":
    unittest.main()

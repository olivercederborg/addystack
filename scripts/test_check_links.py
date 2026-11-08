"""check-links.py fails on a link to a missing file or heading, and skips examples."""
import pathlib, shutil, subprocess, tempfile, textwrap, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-links.py"


class CheckLinks(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts" / SCRIPT.name)
        (self.root / "scripts" / "copies.txt").write_text("")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
        subprocess.run(["git", "-C", str(self.root), "add", name], check=True)

    def run_check(self):
        return subprocess.run([str(self.root / "scripts" / SCRIPT.name)], capture_output=True, text=True)

    def test_passes_when_every_link_resolves(self):
        self.write("skills/a/x/SKILL.md", """\
            See [notes](references/notes.md#the-part) and [web](https://example.com).
            The spec is [here](#usage).

            ## Usage
            """)
        self.write("skills/a/x/references/notes.md", "# Notes\n\n## The part\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_names_a_missing_file_and_a_missing_heading(self):
        self.write("skills/a/x/SKILL.md", "See [gone](references/gone.md) and [part](references/notes.md#nope).\n")
        self.write("skills/a/x/references/notes.md", "# Notes\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/a/x/SKILL.md:1: references/gone.md (no such file)", result.stdout)
        self.assertIn("skills/a/x/SKILL.md:1: references/notes.md#nope (no such heading)", result.stdout)

    def test_skips_examples_in_code_and_other_placeholders(self):
        self.write("skills/a/x/SKILL.md", """\
            An image is `![Before](./before.png)`.

            ````markdown
            [EX-12](link)
            ```
            [inner](also-gone.md)
            ```
            ````

            Hello [{{user}}]({{user}}.md).
            """)
        self.assertEqual(self.run_check().returncode, 0)

    def test_a_kit_placeholder_resolves_from_the_addystack_skill(self):
        self.write("skills/primitive/addystack/principles/one.md", "# One\n")
        self.write("skills/primitive/addystack/core/principles.md",
                   "[one]({{kit}}/principles/one.md) and [two]({{kit}}/principles/two.md)\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("principles/one.md", result.stdout)
        self.assertIn("{{kit}}/principles/two.md (no such file)", result.stdout)

    def test_shared_sources_are_checked_through_their_copies(self):
        self.write("shared/notes.md", "[spec](references/spec.md)\n")
        self.assertEqual(self.run_check().returncode, 0)


if __name__ == "__main__":
    unittest.main()

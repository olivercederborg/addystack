"""Tests for sync-notes.py: every core skill carries shared/notes-line.md's line near its top
(plan D15), no other skill carries it, and the write mode puts it under the title. Each
case runs the script on a scratch kit."""
import pathlib, shutil, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "sync-notes.py"
KIT = SCRIPT.parent.parent
# The addystack skill's folder, which holds lib/ and the release list.
TOOL = pathlib.Path("skills", "primitive", "addystack")
LINE = "**Notes**: read the note."


class SyncNotes(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for folder, source in [("scripts", SCRIPT), (TOOL / "lib", KIT / TOOL / "lib" / "skill_layer.py")]:
            (self.root / folder).mkdir(parents=True)
            shutil.copy(source, self.root / folder)
        (self.root / "shared").mkdir()
        (self.root / "shared" / "notes-line.md").write_text(LINE + "\n")

    def skill(self, name, layer, body):
        (self.root / "skills" / layer / name).mkdir(parents=True)
        path = self.root / "skills" / layer / name / "SKILL.md"
        path.write_text(f"---\nname: {name}\ndescription: x\nmetadata:\n  layer: {layer}\n---\n{body}")
        return path

    def run_sync(self, *args):
        return subprocess.run([sys.executable, str(self.root / "scripts" / SCRIPT.name), *args],
                              capture_output=True, text=True)

    def assert_check_fails(self, *expected):
        result = self.run_sync("--check")
        self.assertEqual(result.returncode, 1, result.stdout)
        for text in expected:
            self.assertIn(text, result.stdout)

    def test_passes_when_each_core_skill_has_the_line_under_its_title(self):
        self.skill("build", "primitive", f"\n# Build\n\n{LINE}\n\n## 1. Load\n")
        self.skill("autopilot", "orchestrator", f"{LINE}\n\nBody.\n")
        self.skill("bro", "optional", "\n# Bro\n")
        result = self.run_sync("--check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_fails_naming_a_core_skill_without_the_line(self):
        self.skill("build", "primitive", "\n# Build\n\n## 1. Load\n")
        self.assert_check_fails("build/SKILL.md")

    def test_fails_when_the_line_is_below_the_first_section(self):
        self.skill("build", "primitive", f"\n# Build\n\n## 1. Load\n\n{LINE}\n")
        self.assert_check_fails("build/SKILL.md")

    def test_fails_when_the_line_has_drifted(self):
        self.skill("build", "primitive", "\n# Build\n\n**Notes**: an older wording.\n")
        self.assert_check_fails("build/SKILL.md")

    def test_fails_when_a_skill_that_isnt_core_has_the_line(self):
        self.skill("bro", "optional", f"\n# Bro\n\n{LINE}\n")
        self.assert_check_fails("bro/SKILL.md")

    def test_write_puts_the_line_under_the_title_and_fixes_drift(self):
        titled = self.skill("build", "primitive", "\n# Build\n\n**Notes**: an older wording.\n\n## 1. Load\n")
        untitled = self.skill("tidy", "primitive", "Review the diff.\n")
        optional = self.skill("bro", "optional", f"\n# Bro\n\n{LINE}\n\nBody.\n")
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertTrue(titled.read_text().endswith(f"---\n\n# Build\n\n{LINE}\n\n## 1. Load\n"))
        self.assertTrue(untitled.read_text().endswith(f"---\n{LINE}\n\nReview the diff.\n"))
        self.assertTrue(optional.read_text().endswith("---\n\n# Bro\n\nBody.\n"))
        self.assertEqual(self.run_sync("--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()

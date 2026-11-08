"""Tests for check-skill-size.sh: a SKILL.md at the limit passes, one byte over fails,
and one oversized skill fails the run even among valid ones."""
import pathlib, shutil, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-skill-size.sh"


def run(sizes):
    root = pathlib.Path(tempfile.mkdtemp())
    try:
        (root / "scripts").mkdir()
        shutil.copy(SCRIPT, root / "scripts")
        for name, size in sizes.items():
            (root / "skills" / "primitive" / name).mkdir(parents=True)
            (root / "skills" / "primitive" / name / "SKILL.md").write_text("x" * size)
        return subprocess.run([str(root / "scripts" / SCRIPT.name)], capture_output=True, text=True)
    finally:
        shutil.rmtree(root)


class CheckSkillSize(unittest.TestCase):
    def test_passes_at_the_limit(self):
        self.assertEqual(run({"a": 14100}).returncode, 0)

    def test_fails_one_byte_over(self):
        result = run({"a": 14101})
        self.assertEqual(result.returncode, 1)
        self.assertIn("a/SKILL.md is 14101 bytes", result.stderr)

    def test_fails_when_one_skill_among_valid_ones_is_over(self):
        self.assertEqual(run({"a": 100, "b": 20000, "c": 100}).returncode, 1)


if __name__ == "__main__":
    unittest.main()

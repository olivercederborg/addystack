"""Tests for check-install.py's comparison: a file the install lacks or holds with other
bytes is named, a symlink in either tree is named, and the checkout's untracked caches
don't count; and its hidden-skill check: each skill outside the release's layers is
named when a plain install adds it or a named one doesn't."""
import importlib.util, pathlib, shutil, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-install.py"
spec = importlib.util.spec_from_file_location("check_install", SCRIPT)
check_install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_install)


class Lost(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.checkout, self.installed = self.root / "kit/skill", self.root / "home/skill"
        for path in ["SKILL.md", "references/format.md", "scripts/github.sh"]:
            for tree in (self.checkout, self.installed):
                (tree / path).parent.mkdir(parents=True, exist_ok=True)
                (tree / path).write_text(path)

    def test_an_identical_install_loses_nothing(self):
        (self.checkout / "scripts/__pycache__").mkdir()
        (self.checkout / "scripts/__pycache__/x.pyc").write_text("cache")
        self.assertEqual(check_install.lost(self.checkout, self.installed), [])

    def test_names_a_missing_file_a_changed_one_and_a_symlink(self):
        (self.installed / "scripts/github.sh").unlink()
        (self.installed / "references/format.md").write_text("other")
        (self.checkout / "references/views.md").symlink_to("format.md")
        self.assertEqual(check_install.lost(self.checkout, self.installed),
                         ["references/format.md (differs)", "references/views.md (a symlink in the checkout)",
                          "scripts/github.sh (missing)"])



class Hidden(unittest.TestCase):
    def test_unshipped_lists_the_preferences_and_preset_skills(self):
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for name, layer in [("build", "primitive"), ("bro", "optional"), ("my-inbox", "preferences"),
                            ("verify-acme", "preset")]:
            path = root / "skills" / layer / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\nname: {name}\nmetadata:\n  layer: {layer}\n---\n")
        self.assertEqual(check_install.unshipped(root), ["my-inbox", "verify-acme"])

    def test_a_hidden_skill_must_stay_out_of_a_plain_install_and_come_in_by_name(self):
        hidden = ["my-inbox", "verify-acme"]
        self.assertEqual(check_install.hidden_problems(hidden, {"build"}, {"build", *hidden}), [])
        self.assertEqual(check_install.hidden_problems(hidden, {"build", "my-inbox"}, {"build", "my-inbox"}),
                         ["my-inbox: a plain install added it; set metadata.internal: true in its SKILL.md",
                          "verify-acme: not installed when --skill names it"])


class ScratchEnv(unittest.TestCase):
    def test_a_callers_install_path_overrides_point_into_the_scratch_home(self):
        caller = {"PATH": "/bin", "CLAUDE_CONFIG_DIR": "/real/claude", "CODEX_HOME": "/real/codex",
                  "XDG_STATE_HOME": "/real/state"}
        env = check_install.scratch_env(caller, "/tmp/h")
        self.assertEqual((env["HOME"], env["CLAUDE_CONFIG_DIR"], env["CODEX_HOME"], env["XDG_STATE_HOME"]),
                         ("/tmp/h", "/tmp/h/.claude", "/tmp/h/.codex", "/tmp/h/.local/state"))
        self.assertEqual(env["PATH"], "/bin")


if __name__ == "__main__":
    unittest.main()

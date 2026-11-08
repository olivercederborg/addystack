"""Tests for sync-skill-list.py: core/skills.json lists every skill a release ships with its
layer, and only those (plan D9). Each case but the first runs the script on a scratch kit."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "sync-skill-list.py"
KIT = SCRIPT.parent.parent
# The addystack skill's folder, which holds lib/ and the release list.
TOOL = pathlib.Path("skills", "primitive", "addystack")


class SyncSkillList(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for folder, source in [("scripts", SCRIPT), (TOOL / "lib", KIT / TOOL / "lib" / "skill_layer.py")]:
            (self.root / folder).mkdir(parents=True)
            shutil.copy(source, self.root / folder)
        (self.root / TOOL / "core").mkdir(parents=True)

    def skill(self, name, layer):
        (self.root / "skills" / layer / name).mkdir(parents=True)
        (self.root / "skills" / layer / name / "SKILL.md").write_text(f"---\nname: {name}\nmetadata:\n  layer: {layer}\n---\n")

    def run_sync(self, *args, root=None):
        return subprocess.run([sys.executable, str((root or self.root) / "scripts" / SCRIPT.name), *args],
                              capture_output=True, text=True)

    def test_the_kits_list_is_in_sync(self):
        result = self.run_sync("--check", root=KIT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lists_the_shipped_layers_only_and_check_fails_until_written(self):
        for name, layer in [("build", "primitive"), ("autopilot", "orchestrator"), ("bro", "optional"),
                            ("my-inbox", "preferences"), ("team-verify", "preset")]:
            self.skill(name, layer)
        self.assertEqual(self.run_sync("--check").returncode, 1)
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertEqual(json.loads((self.root / TOOL / "core" / "skills.json").read_text()),
                         {"skills": {"autopilot": "orchestrator", "bro": "optional", "build": "primitive"}})
        self.assertEqual(self.run_sync("--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()

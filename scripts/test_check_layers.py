"""Tests for check-layers.py: a skill names only skills in its own layer or a lower one
(primitive < orchestrator < optional), preferences and preset skills name anything, and
no core skill names them. Each case runs the script on a scratch kit."""
import pathlib, shutil, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-layers.py"
LAYERS = {"build": "primitive", "tidy": "primitive", "autopilot": "orchestrator",
          "coordinator": "orchestrator", "reply-shape": "optional", "my-inbox": "preferences",
          "verify-acme": "preset"}


class CheckLayers(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts")
        lib = self.root / "skills" / "primitive" / "addystack" / "lib"
        lib.mkdir(parents=True)
        shutil.copy(SCRIPT.parent.parent / "skills" / "primitive" / "addystack" / "lib" / "skill_layer.py", lib)
        for name, layer in LAYERS.items():
            self.skill(name, layer)

    def skill(self, name, layer, body="", metadata=None):
        """The skill's SKILL.md in skills/<layer>/<name>/, replacing one in another layer's folder."""
        for other in self.root.glob(f"skills/*/{name}"):
            if other.parent.name != layer:
                shutil.rmtree(other)
        folder = self.root / "skills" / layer / name
        folder.mkdir(parents=True, exist_ok=True)
        meta = f"metadata:\n  layer: {layer}\n" if metadata is None else metadata
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n{meta}---\n\n{body}\n")

    def run_lint(self):
        return subprocess.run([sys.executable, str(self.root / "scripts" / SCRIPT.name)],
                              capture_output=True, text=True)

    def assert_passes(self):
        result = self.run_lint()
        self.assertEqual(result.returncode, 0, result.stdout)

    def assert_fails(self, *expected):
        result = self.run_lint()
        self.assertEqual(result.returncode, 1, result.stdout)
        for text in expected:
            self.assertIn(text, result.stdout)

    def test_the_kit_passes(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_primitive_naming_autopilot_fails(self):
        self.skill("build", "primitive", "Read the plan, or autopilot's brief.")
        self.assert_fails("build/SKILL.md:8: build (primitive) names autopilot (orchestrator)")

    def test_a_core_skill_naming_reply_shape_fails(self):
        self.skill("build", "primitive", "As in `~/.agents/skills/reply-shape/references/views.md`.")
        self.skill("autopilot", "orchestrator", "A gate is reply-shape's decision card.")
        self.assert_fails("build (primitive) names reply-shape (optional)",
                          "autopilot (orchestrator) names reply-shape (optional)")

    def test_a_core_skill_naming_a_preferences_or_preset_skill_fails(self):
        self.skill("reply-shape", "optional", "Run `my-inbox` first, then verify-acme.")
        self.assert_fails("reply-shape (optional) names my-inbox (preferences)",
                          "reply-shape (optional) names verify-acme (preset)")

    def test_preferences_and_preset_skills_name_anything(self):
        self.skill("my-inbox", "preferences", "Runs `coordinator`, autopilot, and reply-shape.")
        self.skill("verify-acme", "preset", "Run `my-inbox`, then `build`.")
        self.assert_passes()

    def test_same_and_lower_layers_pass(self):
        self.skill("build", "primitive", "Then run `tidy`.")
        self.skill("autopilot", "orchestrator", "Run `build`, then `coordinator`.")
        self.skill("reply-shape", "optional", "As autopilot shows.")
        self.assert_passes()

    def test_a_higher_name_counts_even_as_a_plain_word(self):
        for body in ("A coordinator's worker has a brief.", "Use `coordinator`.", "Read coordinator/SKILL.md.",
                     "Run\nthe coordinator to own the project.", "Ask Coordinator to own it."):
            with self.subTest(body=body):
                self.skill("build", "primitive", body)
                self.assert_fails("build (primitive) names coordinator (orchestrator)")

    def test_a_primitive_name_as_a_plain_word_passes_anywhere(self):
        self.skill("autopilot", "orchestrator", "The build passes once the tidy pass is correct.")
        self.assert_passes()

    def test_a_longer_name_is_not_a_mention(self):
        self.skill("build", "primitive", "The reply-shape-context hook and autopilots run.")
        self.assert_passes()

    def test_a_linked_shared_file_counts_once_for_every_skill_that_links_it(self):
        (self.root / "shared").mkdir()
        (self.root / "shared" / "format.md").write_text("A decision uses reply-shape's card.\n")
        for name in ("build", "tidy"):
            (self.root / "skills" / "primitive" / name / "references").mkdir()
            (self.root / "skills" / "primitive" / name / "references" / "format.md").symlink_to(
                "../../../../shared/format.md")
        self.assert_fails("shared/format.md:1: build (primitive) and 1 more names reply-shape (optional)")
        self.assertEqual(self.run_lint().stdout.count("shared/format.md"), 1)

    def test_a_reference_file_counts(self):
        (self.root / "skills" / "primitive" / "build" / "references").mkdir()
        (self.root / "skills" / "primitive" / "build" / "references" / "notes.md").write_text("x\nThen autopilot.\n")
        self.assert_fails("build/references/notes.md:2: build (primitive) names autopilot (orchestrator)")

    def test_a_name_in_another_case_fails(self):
        self.skill("build", "primitive", "Run Autopilot to build it.")
        self.assert_fails("names autopilot")

    def test_a_layer_nested_under_another_metadata_key_doesnt_count(self):
        self.skill("build", "primitive", metadata="metadata:\n  extension:\n    layer: preferences\n")
        self.assert_fails("metadata.layer")

    def test_comments_dont_set_the_child_indent(self):
        self.skill("build", "primitive", metadata="metadata:\n    # note\n  extension:\n    layer: preferences\n")
        self.assert_fails("metadata.layer")
        self.skill("build", "primitive", metadata="metadata:\n  layer: primitive  # the lowest layer\n")
        self.assert_passes()

    def test_mismatched_quotes_arent_a_layer(self):
        self.skill("build", "primitive", metadata="metadata:\n  layer: \"preferences'\n")
        self.assert_fails("metadata.layer")

    def test_a_linked_folder_counts(self):
        guide = self.root / "docs" / "guide"
        guide.mkdir(parents=True)
        (guide / "notes.md").write_text("Run autopilot.\n")
        (self.root / "skills" / "primitive" / "build" / "guide").symlink_to(guide)
        self.assert_fails("names autopilot")

    def test_a_missing_or_unknown_layer_fails(self):
        self.skill("tidy", "primitive", metadata="")
        self.skill("build", "core")
        self.assert_fails("tidy/SKILL.md: metadata.layer is None", "build/SKILL.md: metadata.layer is 'core'")

    def test_a_layer_beside_other_metadata_counts(self):
        self.skill("build", "optional", "Then autopilot.",
                   metadata="metadata:\n  author: someone\n  layer: optional\n")
        self.assert_passes()

    def test_the_tools_router_and_hooks_arent_the_addystack_skills_text(self):
        self.skill("addystack", "primitive", "Set up the kit.")
        tool = self.root / "skills" / "primitive" / "addystack"
        for path in ("core/router.md", "hooks/README.md"):
            (tool / path).parent.mkdir(parents=True)
            (tool / path).write_text("Route a project to coordinator, a plan to autopilot.\n")
        self.assert_passes()
        (tool / "references").mkdir()
        (tool / "references" / "setup.md").write_text("Then autopilot.\n")
        self.assert_fails("skills/primitive/addystack/references/setup.md:1: addystack (primitive) names autopilot")

    def test_a_skill_in_another_layers_folder_fails(self):
        self.skill("build", "orchestrator", metadata="metadata:\n  layer: primitive\n")
        self.assert_fails("skills/orchestrator/build/SKILL.md: metadata.layer is 'primitive'; move the folder to "
                          "skills/primitive/build/")


if __name__ == "__main__":
    unittest.main()

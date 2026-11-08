"""Tests for check-neutral.py: kit text that names a person, their handle, folders, or
machines, a team or its org, or calls the user he or she fails; skipped places,
attribution lines, ignored files, and binaries pass; and a link counts once, as its
target. Each case but the first runs main() on a scratch kit."""
import contextlib, importlib.util, io, os, pathlib, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-neutral.py"
spec = importlib.util.spec_from_file_location("check_neutral", SCRIPT)
neutral = importlib.util.module_from_spec(spec)
spec.loader.exec_module(neutral)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


class CheckNeutral(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.kit = pathlib.Path(folder.name, "kit")
        self.kit.mkdir()
        self.write("skills/primitive/build/SKILL.md", "---\nname: build\nmetadata:\n  layer: primitive\n---\nBuild it.\n")

    def write(self, path, text):
        (self.kit / path).parent.mkdir(parents=True, exist_ok=True)
        (self.kit / path).write_text(text)

    def run_lint(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = neutral.main(self.kit)
        return code, out.getvalue()

    def problems(self):
        code, out = self.run_lint()
        self.assertEqual(code, 1 if out.count("\n") > 1 else 0, out)
        return [line.strip() for line in out.splitlines()[1:]]

    # A Dagger suite loads only part of the kit, so there the neutral check runs this on all of it.
    @unittest.skipUnless((SCRIPT.parent.parent / ".git").exists(), "not a git checkout")
    def test_the_kit_passes(self):
        run = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=ENV)
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertEqual(run.stdout, "kit text neutral\n")

    def test_a_file_that_names_a_user_fails(self):
        # Check 6's name half: a person, their handle, folders, and machines, and a team and its org.
        self.write("shared/format.md", "Ask Oliver first.\nSee ~/Developer/personal/skills.\n"
                                       "Run it on the devbox.\nIn a Franklin repo,\n"
                                       "git@github.com:hifranklin-tech/app.git\n/Users/olivercederborg/x\n")
        self.assertEqual(self.problems(), [
            "shared/format.md:1: Oliver", "shared/format.md:2: Developer/personal",
            "shared/format.md:3: devbox", "shared/format.md:4: Franklin",
            "shared/format.md:5: hifranklin", "shared/format.md:6: olivercederborg"])

    def test_names_fail_in_code_and_any_case(self):
        self.write("hooks/a.py", 'MESSAGE = "tell OLIVER"  # a franklin push\n')
        self.assertEqual(self.problems(), ["hooks/a.py:1: OLIVER, franklin"])

    def test_pronouns_fail_and_words_holding_them_pass(self):
        self.write("principles/ask.md", "Hand him a step.\nThis is their call, not hers.\n"
                                        "She decides. Other theme, shell, history, where.\n")
        self.assertEqual(self.problems(), ["principles/ask.md:1: him", "principles/ask.md:2: hers",
                                           "principles/ask.md:3: She"])

    def test_the_skipped_places_pass(self):
        for path in ["docs/plans/a.md", "evals/build/README.md", "maintainer/scorecard.py",
                     "global/shared.md", "router.md",
                     "replies.md", "taste.md", "principles/index.md", "LICENSE", "principles/NOTICE"]:
            self.write(path, "Oliver's Franklin devbox; ask him.\n")
        self.write("skills/preferences/my-inbox/SKILL.md", "---\nname: my-inbox\nmetadata:\n  layer: preferences\n---\nOliver's.\n")
        self.write("skills/preset/verify-team/SKILL.md", "---\nname: verify-team\nmetadata:\n  layer: preset\n---\nFranklin.\n")
        self.assertEqual(self.problems(), [])

    def test_the_kits_repo_passes_and_the_readme_counts(self):
        self.write("README.md", "npx skills add olivercederborg/addystack -g\nAsk Oliver.\n"
                                "See olivercederborg/skills.\n")
        self.assertEqual(self.problems(), ["README.md:2: Oliver", "README.md:3: olivercederborg"])

    def test_the_same_names_fail_outside_the_skips(self):
        for path in ["docsx/a.md", "scripts/README.md", "router/a.md", "skills/primitive/build/references/LICENSES.md"]:
            self.write(path, "Oliver\n")
        self.assertEqual(self.problems(), ["docsx/a.md:1: Oliver", "router/a.md:1: Oliver", "scripts/README.md:1: Oliver",
                                           "skills/primitive/build/references/LICENSES.md:1: Oliver"])

    def test_only_the_folder_skips_a_skill(self):
        # A preferences skill in a core layer's folder still counts; check-layers.py fails its folder.
        self.write("skills/primitive/new-skill/SKILL.md", "---\nname: new-skill\nmetadata:\n  layer: preferences\n"
                                                         "---\nAsk Oliver.\n")
        self.assertEqual(self.problems(), ["skills/primitive/new-skill/SKILL.md:6: Oliver"])

    def test_attribution_lines_pass(self):
        self.write("skills/primitive/tidy/references/a.md", "Adapted from a post by Oliver.\nCopyright (c) 2026 Oliver\n"
                                           "metadata:\n  author: Oliver (@olivercederborg)\nThanks, Oliver.\n")
        self.assertEqual(self.problems(), ["skills/primitive/tidy/references/a.md:5: Oliver"])

    def test_a_link_counts_once_as_its_target_even_in_a_skip(self):
        self.write("shared/taste.md", "Oliver's taste\n")
        self.write("docs/workflow.md", "How Oliver builds\n")
        self.write("docs/history.md", "Oliver, in 2025\n")
        for skill in ["build", "tidy"]:
            references = self.kit / "skills" / "primitive" / skill / "references"
            references.mkdir(parents=True, exist_ok=True)
            (references / "taste.md").symlink_to("../../../../shared/taste.md")
            (references / "workflow.md").symlink_to("../../../../docs/workflow.md")
        self.assertEqual(self.problems(), ["docs/workflow.md:1: Oliver", "shared/taste.md:1: Oliver"])

    def test_binary_files_pass(self):
        (self.kit / "skills" / "optional" / "review-artifact").mkdir(parents=True)
        (self.kit / "skills" / "optional" / "review-artifact" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfeOliver")
        self.assertEqual(self.problems(), [])

    def test_git_ignored_files_pass_and_untracked_ones_count(self):
        subprocess.run(["git", "init", "-q", str(self.kit)], check=True, env=ENV)
        self.write(".gitignore", "handoff.md\n")
        self.write("handoff.md", "For Oliver.\n")
        self.write("decisions.tsv", "Oliver's call\n")
        self.assertEqual(self.problems(), ["decisions.tsv:1: Oliver"])

    def test_a_linked_folder_into_a_skip_counts_in_git_and_without_it(self):
        self.write("docs/guide/notes.md", "Ask Oliver.\n")
        (self.kit / "skills" / "primitive" / "build" / "guide").symlink_to(self.kit / "docs" / "guide")
        self.assertEqual(self.problems(), ["docs/guide/notes.md:1: Oliver"])
        subprocess.run(["git", "init", "-q", str(self.kit)], check=True, env=ENV)
        self.assertEqual(self.problems(), ["docs/guide/notes.md:1: Oliver"])

    def test_a_line_that_only_mentions_copyright_still_counts(self):
        self.write("shared/format.md", "Ask Oliver to update the Copyright notice.\nAdapted from Oliver's kit.\n")
        self.assertEqual(self.problems(), ["shared/format.md:1: Oliver"])


if __name__ == "__main__":
    unittest.main()

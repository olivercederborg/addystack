"""Tests for bin/addystack with every ADDYSTACK_* path in a temp folder: build writes the
built files and --check and --dry-run only compare, a config typo fails build --check and
doctor with its key path, print-config and policy print JSON, and policy gives each kind
of checkout its trust."""
from __future__ import annotations

import json, os, pathlib, re, subprocess, sys, tempfile, unittest, unittest.mock

KIT = pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack"
BIN = KIT / "bin" / "addystack"
sys.path[:0] = [str(KIT / "lib"), str(KIT / "hooks")]
import config  # noqa: E402
import hookset  # noqa: E402

USER = """// A user's config.
{
  "identity": { "name": "Sam" },
  "policy": {
    "defaults": { "planning": "autonomous", "trust": "merge-on-go" },
    "repos": [
      { "match": { "remote": "/(blog|site)" }, "trust": "gate" },
      { "match": { "remote": "[:/]acme-team/" }, "planning": "gated", "trust": "draft", "pushVia": "gh-stack",
        "issues": "linear", "lenses": ["team-conventions"], "verifySkill": "verify-team", "decisionsSection": true }
    ]
  },
  "replies": { "style": "reply-shape", "rules": "replies.md", "next": "lettered", "turnBlock": true },
  "instructions": "global.md"
}
"""


class Cli(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = pathlib.Path(folder.name).resolve()
        self.config = self.dir / "config" / "addystack.jsonc"
        self.config.parent.mkdir()
        self.config.write_text(USER)
        (self.config.parent / "replies.md").write_text("rules")
        (self.config.parent / "global.md").write_text("# Actions\n\n- Sam's action.\n")
        self.state = self.dir / "state"
        self.claude = self.dir / "claude" / "CLAUDE.md"
        self.codex = self.dir / "codex" / "AGENTS.md"
        self.env = {**os.environ, "ADDYSTACK_CONFIG": str(self.config), "ADDYSTACK_STATE": str(self.state),
                    "ADDYSTACK_CLAUDE_MD": str(self.claude), "ADDYSTACK_CODEX_MD": str(self.codex)}
        self.installed_home()

    def installed_home(self):
        """A scratch HOME where doctor's host, skill, hook, and tool checks pass: stub
        `claude`, `codex`, and `gh` first on PATH, both skill folders linked to the kit as a
        maintainer's are, Claude Code's work-verifier agent linked to verify-work's, and the
        selected hooks in both hosts' settings."""
        home, stubs = self.dir / "home", self.dir / "stubs"
        stubs.mkdir()
        for name in ("claude", "codex", "gh"):
            (stubs / name).write_text("#!/bin/sh\necho 1.0\n")
            (stubs / name).chmod(0o755)
        for folder in (".claude/skills", ".agents/skills"):
            (home / folder).parent.mkdir(parents=True, exist_ok=True)
            (home / folder).symlink_to(KIT)
        (home / ".claude/agents").mkdir()
        (home / ".claude/agents/work-verifier.md").symlink_to(KIT.parent / "verify-work/agents/work-verifier.md")
        # Under the scratch HOME, as doctor runs, so a kit path renders the same way.
        with unittest.mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude")}):
            value = config.resolve(self.config)
            for runtime in hookset.RUNTIMES:
                target = hookset.settings_path(runtime)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"hooks": hookset.render(hookset.select(value, runtime))}))
        self.env.update({"HOME": str(home), "XDG_STATE_HOME": str(home / ".local/state"),
                         "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                         "PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"})

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(BIN), *args], capture_output=True, text=True, env=self.env)

    def repo(self, origin=None):
        path = pathlib.Path(tempfile.mkdtemp(dir=self.dir))
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        if origin:
            subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
        return path

    def built(self):
        return [self.state / "resolved.json", self.state / "router.md", self.state / "principles.md",
                self.claude, self.codex]


class Build(Cli):
    def test_writes_each_built_file_then_check_passes(self):
        self.assertEqual(self.run_cli("build").returncode, 0)
        for path in self.built():
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
        self.assertEqual(json.loads((self.state / "resolved.json").read_text())["identity"]["name"], "Sam")
        self.assertIn("- Sam's action.", self.claude.read_text())
        self.assertEqual(self.run_cli("build", "--check").returncode, 0)

    def test_check_names_each_stale_file_and_writes_nothing(self):
        self.run_cli("build")
        self.codex.write_text("edited")
        result = self.run_cli("build", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.codex), result.stderr)
        self.assertNotIn(str(self.claude), result.stderr)
        self.assertEqual(self.codex.read_text(), "edited")

    def test_dry_run_prints_diffs_and_writes_nothing(self):
        result = self.run_cli("build", "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"+++ {self.claude}", result.stdout)
        self.assertIn("would write 5 files", result.stdout)
        self.assertFalse(self.state.exists() or self.claude.exists() or self.codex.exists())

    def test_a_link_is_replaced_not_written_through(self):
        target = self.dir / "kit-built.md"
        target.write_text("the kit's file")
        self.claude.parent.mkdir()
        self.claude.symlink_to(target)
        self.run_cli("build")
        self.assertFalse(self.claude.is_symlink())
        self.assertEqual(target.read_text(), "the kit's file")

    def test_a_link_to_the_built_text_still_counts_as_stale(self):
        self.run_cli("build")
        target = self.dir / "kit-built.md"
        self.claude.rename(target)
        self.claude.symlink_to(target)
        self.assertEqual(self.run_cli("build", "--check").returncode, 1)
        self.run_cli("build")
        self.assertFalse(self.claude.is_symlink())

    def test_doctor_and_build_check_agree_on_freshness(self):
        state = self.state / "resolved.json"

        def link():
            state.rename(self.dir / "saved.json")
            state.symlink_to(self.dir / "saved.json")

        def lock():
            state.chmod(0)
            self.addCleanup(state.chmod, 0o644)

        cases = [("fresh", lambda: None, 0), ("edited", lambda: state.write_text(state.read_text() + " "), 1),
                 ("linked", link, 1), ("unreadable", lock, 1)]
        for name, change, code in cases:
            with self.subTest(name):
                self.run_cli("build")
                change()
                self.assertEqual(self.run_cli("build", "--check").returncode, code)
                self.assertEqual(self.run_cli("doctor").returncode, code)

    def test_an_unreadable_built_file_is_rewritten_without_a_traceback(self):
        self.run_cli("build")
        self.codex.chmod(0)
        self.addCleanup(lambda: self.codex.exists() and self.codex.chmod(0o644))
        dry = self.run_cli("build", "--dry-run")
        self.assertEqual((dry.returncode, dry.stderr), (0, ""))
        self.assertIn(str(self.codex), dry.stdout)
        self.assertEqual(self.run_cli("build").returncode, 0)
        self.assertEqual(self.run_cli("build", "--check").returncode, 0)

    def test_bad_usage_exits_2(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("build", "--check", "--dry-run").returncode, 2)
        self.assertEqual(self.run_cli("policy").returncode, 2)


class Typo(Cli):
    def setUp(self):
        super().setUp()
        self.config.write_text(USER.replace('"reply-shape"', '"reply-shap"'))

    def test_build_check_names_the_key_path(self):
        result = self.run_cli("build", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn('replies.style: "reply-shap" is not one of reply-shape, own', result.stderr)

    def test_doctor_names_the_key_path(self):
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL  config: replies.style:", result.stdout)
        self.assertIn("skip  built files: skipped", result.stdout)


class Extends(Cli):
    """A config from before the kit dropped presets still names extends (plan D5)."""

    def setUp(self):
        super().setUp()
        self.config.write_text(USER.replace('"identity"', '"extends": ["team"],\n  "identity"'))

    def test_each_command_names_the_key_and_what_to_do(self):
        for args, stream in [(("doctor",), "stdout"), (("print-config",), "stderr"), (("build", "--check"), "stderr")]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("extends: removed: the kit ships no presets. Put each preset rule first in "
                              "policy.repos[]", getattr(result, stream))

    def test_doctor_reports_it_as_the_config_check(self):
        self.assertIn("FAIL  config: extends: removed", self.run_cli("doctor").stdout)


class Doctor(Cli):
    def test_passes_after_a_build_with_every_check(self):
        self.run_cli("build")
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ok    built files: match the config", result.stdout)
        for name in ("hosts", "skill links", "agent", "hooks", "policy tools"):
            self.assertRegex(result.stdout, rf"(?m)^ok    {name}: ")

    def test_fails_when_the_built_files_are_stale(self):
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL  built files: out of date", result.stdout)


class Notes(Cli):
    """A note in the config folder's notes/ is built beside resolved.json (plan D15, check 12)."""

    def setUp(self):
        super().setUp()
        self.notes = self.config.parent / "notes"
        self.notes.mkdir()
        self.note("verify-work", "- Also run `make lint`.\n")
        self.built_note = self.state / "notes" / "verify-work.md"

    def note(self, skill, text):
        (self.notes / f"{skill}.md").write_text(text)

    def test_build_writes_the_note_then_check_passes(self):
        self.assertEqual(self.run_cli("build").returncode, 0)
        text = self.built_note.read_text()
        self.assertIn("- Also run `make lint`.", text)
        self.assertIn(f"from {self.notes / 'verify-work.md'}", text)
        self.assertEqual(self.run_cli("build", "--check").returncode, 0)

    def test_check_names_a_stale_note_and_writes_nothing(self):
        self.run_cli("build")
        self.note("verify-work", "- Also run `make test`.\n")
        result = self.run_cli("build", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.built_note), result.stderr)
        self.assertIn("make lint", self.built_note.read_text())
        self.assertIn("make test", self.run_cli("build", "--dry-run").stdout)

    def test_a_built_note_without_its_source_is_removed(self):
        self.run_cli("build")
        (self.notes / "verify-work.md").unlink()
        self.assertIn(str(self.built_note), self.run_cli("build", "--check").stderr)
        dry = self.run_cli("build", "--dry-run")
        self.assertIn("would remove 1 file", dry.stdout)
        self.assertTrue(self.built_note.exists())
        self.assertIn(f"removed {self.built_note}", self.run_cli("build").stdout)
        self.assertFalse(self.built_note.exists())
        self.assertEqual(self.run_cli("build", "--check").returncode, 0)

    def test_a_note_for_a_skill_that_isnt_core_is_not_built(self):
        self.note("no-such-skill", "- x\n")
        self.note("reply-shape", "- x\n")
        self.run_cli("build")
        self.assertEqual(sorted(path.name for path in (self.state / "notes").iterdir()), ["verify-work.md"])

    def test_a_note_under_a_renamed_skills_old_name_keeps_applying(self):
        self.note("review-teammate-pr", "- Ask about the migration.\n")
        self.run_cli("build")
        built = self.state / "notes" / "review-code.md"
        self.assertIn("- Ask about the migration.", built.read_text())
        self.assertFalse((self.state / "notes" / "review-teammate-pr.md").exists())
        self.assertEqual(self.run_cli("doctor").returncode, 0)
        # Beside a note under the new name, the old one is named for the user to fold in.
        self.note("review-code", "- Check the tests.\n")
        self.run_cli("build")
        self.assertIn("- Check the tests.", built.read_text())
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("review-teammate-pr.md is for review-teammate-pr, which is review-code now", result.stdout)

    def test_a_note_built_under_the_old_name_still_shows_a_changed_skill(self):
        self.note("review-teammate-pr", "- Ask about the migration.\n")
        self.run_cli("build")
        # As if the last build ran before the rename, against an older skill.
        built = self.state / "notes" / "review-code.md"
        old = self.state / "notes" / "review-teammate-pr.md"
        old.write_text(re.sub(r"sha256 [0-9a-f]{64}", "sha256 " + "0" * 64, built.read_text()))
        built.unlink()
        result = self.run_cli("doctor")
        self.assertIn("FAIL  notes: review-code changed since", result.stdout)

    def test_doctor_passes_with_a_built_note(self):
        self.run_cli("build")
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ok    notes: verify-work", result.stdout)

    def test_doctor_flags_a_note_for_a_skill_that_doesnt_exist(self):
        self.note("no-such-skill", "- x\n")
        self.run_cli("build")
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"FAIL  notes: {self.notes / 'no-such-skill.md'} names no core skill no-such-skill", result.stdout)
        self.assertIn("ok    built files", result.stdout)

    def test_doctor_flags_a_note_whose_skill_changed_since_the_build(self):
        self.run_cli("build")
        # As if the build ran against an older verify-work: its recorded hash differs.
        text = self.built_note.read_text()
        self.built_note.write_text(re.sub(r"sha256 [0-9a-f]{64}", "sha256 " + "0" * 64, text))
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL  notes: verify-work changed since", result.stdout)
        self.assertIn("reread", result.stdout)


    def test_a_state_notes_folder_linked_to_the_config_notes_builds_and_removes_nothing(self):
        self.note("retired-skill", "private note\n")
        self.note("built-before", "<!-- Built by addystack build from an earlier run -->\n")
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "notes").symlink_to(self.notes)
        self.run_cli("build")
        self.assertEqual((self.notes / "retired-skill.md").read_text(), "private note\n")
        self.assertEqual((self.notes / "verify-work.md").read_text(), "- Also run `make lint`.\n")
        self.assertTrue((self.notes / "built-before.md").exists())
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("so notes aren't built", result.stdout)

    def test_the_skill_hash_covers_every_file_in_the_skill_folder(self):
        sys.path[:0] = [str(KIT / "lib"), str(KIT / "hooks")]
        import notes
        skill = pathlib.Path(self.config.parent, "kit-skill")
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("x\n")
        (skill / "references" / "a.md").write_text("one\n")
        before = notes._digest(skill / "SKILL.md")
        (skill / "references" / "a.md").write_text("two\n")
        self.assertNotEqual(before, notes._digest(skill / "SKILL.md"))


class PrintConfig(Cli):
    def test_prints_the_resolved_config(self):
        resolved = json.loads(self.run_cli("print-config").stdout)
        self.assertEqual(resolved["layers"], ["defaults", "user"])
        self.assertEqual(resolved["replies"]["rules"], str(self.config.parent / "replies.md"))

    def test_layers_prints_each_parsed_layer(self):
        layers = json.loads(self.run_cli("print-config", "--layers").stdout)
        self.assertEqual([layer["name"] for layer in layers], ["defaults", "user"])


class Policy(Cli):
    def setUp(self):
        super().setUp()
        self.run_cli("build")

    def policy(self, path, *args):
        result = self.run_cli("policy", "--repo", str(path), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_each_kind_of_checkout(self):
        cases = [
            (self.repo("https://github.com/acme-team/app.git"), "gated", "draft", "gh-stack"),
            (self.repo("https://github.com/sam/skills.git"), "autonomous", "merge-on-go", "git"),
            (self.repo("https://github.com/sam/blog.git"), "autonomous", "gate", "git"),
            (self.dir, "autonomous", "merge-on-go", "git"),
        ]
        for path, planning, trust, push in cases:
            with self.subTest(path=path):
                policy = self.policy(path)
                self.assertEqual((policy["planning"], policy["trust"], policy["pushVia"]), (planning, trust, push))

    def test_explain_names_the_rules_that_matched(self):
        policy = self.policy(self.repo("git@github.com:acme-team/x.git"), "--explain")
        self.assertEqual(policy["matched"], ["user#1"])
        [rule] = policy["explain"]["rules"]
        self.assertEqual(rule["match"], {"remote": "[:/]acme-team/"})

    def test_an_unreadable_origin_is_unresolved(self):
        path = self.repo()
        subprocess.run(["git", "-C", str(path), "remote", "add", "upstream", "git@github.com:a/b.git"], check=True)
        policy = self.policy(path, "--explain")
        self.assertEqual((policy["planning"], policy["trust"], policy["matched"]), ("gated", "draft", ["unresolved"]))
        self.assertIn("unresolved", policy["explain"])

    def test_explain_shows_the_repo_file(self):
        path = self.repo("https://github.com/sam/skills.git")
        (path / ".agents").mkdir()
        (path / ".agents" / "addystack.jsonc").write_text('{ "planning": "gated", "trust": "merge-on-go" }')
        policy = self.policy(path, "--explain")
        self.assertEqual((policy["planning"], policy["trust"], policy["matched"]),
                         ("gated", "merge-on-go", ["repo-file"]))
        self.assertEqual(policy["explain"]["repoFile"]["path"], str(path / ".agents" / "addystack.jsonc"))
        self.assertEqual(policy["explain"]["repoFile"]["set"], {"planning": "gated", "trust": "merge-on-go"})

    def test_prints_the_repo_files_review_app(self):
        path = self.repo("https://github.com/sam/skills.git")
        (path / ".agents").mkdir()
        (path / ".agents" / "addystack.jsonc").write_text('{ "review": { "app": "frankie-reviewer" } }')
        self.assertEqual(self.policy(path)["review"], {"app": "frankie-reviewer"})
        self.assertIsNone(self.policy(self.repo("https://github.com/sam/other.git"))["review"])

    def test_explain_names_an_invalid_repo_files_issue(self):
        path = self.repo("https://github.com/sam/skills.git")
        (path / ".agents").mkdir()
        (path / ".agents" / "addystack.jsonc").write_text('{ "issues": "linear" }')
        policy = self.policy(path, "--explain")
        self.assertEqual((policy["trust"], policy["matched"]), ("draft", ["unresolved", "repo-file-invalid"]))
        self.assertIn("issues: unknown key", policy["explain"]["repoFile"]["issues"][0])
        self.assertIn("policy file", policy["explain"]["unresolved"])

    def test_without_a_build_it_warns_and_gives_the_kit_defaults(self):
        (self.state / "resolved.json").unlink()
        result = self.run_cli("policy", "--repo", str(self.dir))
        self.assertIn("is missing", result.stderr)
        self.assertEqual(json.loads(result.stdout)["planning"], "gated")


if __name__ == "__main__":
    unittest.main()

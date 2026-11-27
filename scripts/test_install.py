"""Tests for `addystack install` (plan D9, D10) in a scratch HOME: it merges the selected
hooks into each host's settings and keeps every other hook, removes only hooks it
installed earlier, moves hand-written CLAUDE.md and AGENTS.md text into global.md before
the first build, and --dry-run writes nothing; and plan check 9's local part, a fresh
user's install, init --yes, build, and doctor."""
from __future__ import annotations

import json, os, pathlib, shutil, stat, sys, unittest
from pathlib import Path

from addystack_home import BIN, KIT, SKILLS, Home

sys.path[:0] = [str(KIT / "lib"), str(KIT / "hooks")]
import reconcile  # noqa: E402

UNRELATED = {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/bin/my-guard.sh", "timeout": 5}]}


class Hooks(Home):
    def test_adds_the_selected_hooks_from_the_kit_and_keeps_an_unrelated_one(self):
        self.write(self.settings, json.dumps({"model": "opus", "hooks": {"PreToolUse": [UNRELATED]}}))
        self.ok("install")
        settings = self.json(self.settings)
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(settings["hooks"]["PreToolUse"][0], UNRELATED)
        ours = [command for commands in self.commands(self.settings).values() for command in commands
                if command != "~/bin/my-guard.sh"]
        self.assertTrue(ours)
        self.assertTrue(all(command.startswith(f"{KIT}/hooks/") for command in ours), ours)
        self.assertTrue(self.codex_hooks.is_file())
        self.assertEqual(self.json(self.state / "installed.json")["version"], 1)

    def test_a_second_install_changes_no_hooks(self):
        self.ok("install")
        before = self.settings.read_text()
        self.assertNotIn("changed", self.ok("install").stdout)
        self.assertEqual(self.settings.read_text(), before)

    def test_removes_a_hook_it_installed_once_its_no_longer_selected(self):
        self.write(self.config, '{ "hooks": { "preset": "all" } }')
        self.write(self.settings, json.dumps({"hooks": {"SessionStart": [{"hooks": [UNRELATED["hooks"][0]]}]}}))
        self.ok("install")
        self.assertIn(f"{KIT}/hooks/skills-checkout-check.py", self.commands(self.settings)["SessionStart"])
        self.write(self.config, '{ "hooks": { "preset": "all", "disable": ["skills-checkout-check"] } }')
        out = self.ok("install").stdout
        self.assertIn(f"- SessionStart {KIT}/hooks/skills-checkout-check.py", out)
        self.assertNotIn(f"{KIT}/hooks/skills-checkout-check.py", self.commands(self.settings)["SessionStart"])
        self.assertEqual(self.commands(self.settings)["SessionStart"][0], "~/bin/my-guard.sh")

    def test_keeps_a_users_hook_on_a_kit_script_no_manifest_entry_runs(self):
        mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": f"{KIT}/hooks/my-personal-hook.sh"}]}
        self.write(self.settings, json.dumps({"hooks": {"PreToolUse": [mine]}}))
        out = self.ok("install").stdout
        self.assertEqual(self.json(self.settings)["hooks"]["PreToolUse"][0], mine)
        self.assertNotIn("my-personal-hook.sh", out)
        self.assertNotIn("my-personal-hook.sh", self.ok("doctor").stdout)

    def test_removes_a_hook_the_ledger_recorded_from_a_kit_that_moved(self):
        old = "/old/kit/hooks/merge-gate.py"
        self.write(self.settings, json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": old}]}, UNRELATED]}}))
        self.write(self.state / "installed.json", json.dumps({"version": 1, "hooks": {"claude": [["PreToolUse", old]]}}))
        self.ok("install")
        commands = self.commands(self.settings)["PreToolUse"]
        self.assertNotIn(old, commands)
        self.assertIn("~/bin/my-guard.sh", commands)

    def test_re_points_hooks_rendered_for_the_kit_path_the_last_build_recorded(self):
        """A maintainer's kit checkout moved, and no install ever wrote a ledger: hooks that
        run a manifest script from the old kit's hooks folder are replaced, not doubled."""
        old, mine = "/old/kit/hooks/merge-gate.py", "/old/kit/hooks/my-personal-hook.sh"
        self.write(self.settings, json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": old}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": mine}]}, UNRELATED]}}))
        self.write(self.state / "resolved.json", json.dumps({"kit": "/old/kit"}))
        self.ok("install")
        commands = self.commands(self.settings)["PreToolUse"]
        self.assertNotIn(old, commands)
        self.assertIn(f"{KIT}/hooks/merge-gate.py", commands)
        self.assertEqual([c for c in commands if c.endswith("/merge-gate.py")], [f"{KIT}/hooks/merge-gate.py"])
        self.assertIn(mine, commands)
        self.assertIn("~/bin/my-guard.sh", commands)

    def test_a_disabled_host_gets_no_hooks_and_loses_the_ones_it_had(self):
        self.ok("install")
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.ok("install")
        self.assertEqual(self.json(self.codex_hooks), {"hooks": {}})
        self.assertNotIn("codex", self.json(self.state / "installed.json")["hooks"])

    def test_a_settings_file_that_isnt_json_stops_before_any_write(self):
        self.write(self.settings, "{ not json")
        self.write(self.claude_md, "My rules.\n")
        before = self.snapshot()
        result = self.cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("can't read", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_each_replaced_file_keeps_its_mode(self):
        # Under a 022 umask a new file is 644; a private file the user made 600 stays 600.
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.write(self.config.parent / "global.md", "# Mine\n")
        self.write(self.settings, '{ "env": { "API_KEY": "secret" } }')
        self.write(self.claude_md, "# Personal\n\nPrivate rule.\n")
        self.write(self.state / "installed.json", "{}")
        files = [self.config, self.config.parent / "global.md", self.settings, self.claude_md,
                 self.state / "installed.json"]
        for path in files:
            path.chmod(0o600)
        umask = os.umask(0o022)
        try:
            self.ok("install")
        finally:
            os.umask(umask)
        self.assertIn("Private rule.", self.claude_md.read_text())
        self.assertEqual({str(path): oct(stat.S_IMODE(path.stat().st_mode)) for path in files},
                         {str(path): "0o600" for path in files})

    def test_an_invalid_config_stops_before_any_write(self):
        self.write(self.config, '{ "replies": { "style": "reply-shap" } }')
        before = self.snapshot()
        result = self.cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("replies.style", result.stderr)
        self.assertEqual(self.snapshot(), before)


class Instructions(Home):
    def global_md(self):
        return (self.config.parent / "global.md").read_text()

    def test_moves_hand_written_text_into_global_md_before_the_first_build(self):
        self.write(self.claude_md, "# Mine\n\n- Claude rule.\n")
        self.write(self.codex_md, "# Mine\n\n- Codex rule.\n")
        self.ok("install")
        self.assertEqual(self.global_md(), "# Mine\n\n- Claude rule.\n\n# Mine\n\n- Codex rule.\n")
        self.assertTrue(self.claude_md.read_text().startswith("<!-- Built by addystack build"))
        self.assertTrue(self.codex_md.read_text().startswith("<!-- Built by addystack build"))

    def test_without_a_config_the_build_carries_the_moved_text_now_and_later(self):
        self.write(self.claude_md, "# Claude\n\n- Answer in French.\n")
        self.write(self.codex_md, "# Codex\n\n- Run tests first.\n")
        self.ok("install")
        self.assertFalse(self.config.exists())
        for path in (self.claude_md, self.codex_md):
            self.assertIn("- Answer in French.", path.read_text())
            self.assertIn("- Run tests first.", path.read_text())
        self.ok("build", "--check")
        self.write(self.config.parent / "global.md", "# Claude\n\n- Answer in Swedish.\n")
        self.ok("build")
        self.assertIn("- Answer in Swedish.", self.claude_md.read_text())

    def test_the_same_text_in_both_files_moves_once_and_a_second_install_adds_nothing(self):
        self.write(self.claude_md, "Shared rule.\n")
        self.write(self.codex_md, "Shared rule.\n")
        self.ok("install")
        self.ok("install")
        self.assertEqual(self.global_md(), "Shared rule.\n")

    def test_appends_to_an_existing_global_md_under_a_heading_naming_the_source(self):
        self.write(self.config.parent / "global.md", "# Data\n\n- Kept.\n")
        self.write(self.claude_md, "Loose rule.\n")
        self.ok("install")
        self.assertEqual(self.global_md(), "# Data\n\n- Kept.\n\n# From ~/.claude/CLAUDE.md\n\nLoose rule.\n")

    def test_names_global_md_in_a_config_without_instructions_so_the_build_carries_it(self):
        self.write(self.config, '// mine\n{\n  "identity": { "name": "Sam" }\n}\n')
        self.write(self.claude_md, "# Mine\n\n- Kept rule.\n")
        self.ok("install")
        self.assertEqual(self.config.read_text(),
                         '// mine\n{\n  "instructions": "global.md",\n  "identity": { "name": "Sam" }\n}\n')
        self.assertIn("- Kept rule.", self.claude_md.read_text())

    def test_replaces_a_null_instructions(self):
        self.write(self.config, '{ "instructions": null }')
        self.write(self.codex_md, "Codex rule.\n")
        self.ok("install")
        self.assertEqual(self.config.read_text(), '{ "instructions": "global.md" }')
        self.assertIn("Codex rule.", self.codex_md.read_text())

    def test_replaces_the_real_null_instructions_not_one_in_a_comment_or_a_string(self):
        cases = {
            "comment": ('// Example: "instructions": null\n{"instructions":null, "hosts":{"codex":false}}\n',
                        '// Example: "instructions": null\n{"instructions":"global.md", "hosts":{"codex":false}}\n'),
            "string": ('{ "identity": { "name": "\\"instructions\\": null" },\n  /* "instructions": null */ '
                       '"instructions" /* here */ : null }',
                       '{ "identity": { "name": "\\"instructions\\": null" },\n  /* "instructions": null */ '
                       '"instructions" /* here */ : "global.md" }'),
        }
        for name, (before, after) in cases.items():
            with self.subTest(name):
                self.write(self.config, before)
                self.write(self.claude_md, "My original instruction.\n")
                self.ok("install")
                self.assertEqual(self.config.read_text(), after)
                self.assertIn("My original instruction.", self.claude_md.read_text())

    def test_appends_to_the_file_the_config_names(self):
        self.write(self.config, '{ "instructions": "mine.md" }')
        self.write(self.config.parent / "mine.md", "# Old\n")
        self.write(self.claude_md, "# New\n")
        self.ok("install")
        self.assertEqual((self.config.parent / "mine.md").read_text(), "# Old\n\n# New\n")
        self.assertFalse((self.config.parent / "global.md").exists())

    def test_a_host_file_it_cant_read_stops_before_any_write(self):
        def unreadable():
            self.write(self.claude_md, "Private rules.\n").chmod(0)
            self.addCleanup(self.claude_md.chmod, 0o644)

        cases = {"unreadable": unreadable,
                 "not UTF-8": lambda: self.claude_md.write_bytes(b"Private rules \xff\n")}
        for name, make in cases.items():
            with self.subTest(name):
                self.claude_md.parent.mkdir(parents=True, exist_ok=True)
                make()
                result = self.cli("install")
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"can't read {self.claude_md}", result.stderr)
                self.claude_md.chmod(0o644)
                self.assertIn(b"Private rules", self.claude_md.read_bytes())
                for path in (self.config.parent, self.settings, self.codex_hooks, self.state):
                    self.assertFalse(path.exists(), path)

    def test_a_built_file_and_a_disabled_hosts_file_stay_where_they_are(self):
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.write(self.claude_md, "<!-- Built by scripts/build-global.py from global/shared.md. -->\nKit text.\n")
        self.write(self.codex_md, "Codex only.\n")
        self.ok("install")
        self.assertFalse((self.config.parent / "global.md").exists())
        self.assertEqual(self.codex_md.read_text(), "Codex only.\n")


class Agent(Home):
    """With the claude host enabled, install links ~/.claude/agents/work-verifier.md to
    verify-work's copy in Claude's skill folder, the only place npx skills add puts it."""

    def setUp(self):
        super().setUp()
        self.link = self.home / ".claude/agents/work-verifier.md"
        self.source = self.home / ".claude/skills/verify-work/agents/work-verifier.md"

    def test_links_a_missing_path_and_a_second_install_leaves_it(self):
        out = self.ok("install").stdout
        self.assertIn(f"changed {self.link} (agent)\n  links it to ~/.claude/skills/verify-work/agents/"
                      "work-verifier.md\n", out)
        self.assertEqual(os.readlink(self.link), str(self.source))
        self.assertIn("name: work-verifier", self.link.read_text())
        self.assertNotIn(str(self.link), self.ok("install").stdout)

    def test_replaces_a_link_to_the_old_repo_root_path(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/old/kit/agents/work-verifier.md")
        out = self.ok("install").stdout
        self.assertIn("links it to ~/.claude/skills/verify-work/agents/work-verifier.md, not "
                      "/old/kit/agents/work-verifier.md", out)
        self.assertEqual(os.readlink(self.link), str(self.source))

    def test_keeps_files_at_the_old_fixed_temporary_names(self):
        # Install once renamed through `.<name>.addystack-tmp`, deleting whatever was there.
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.write(self.settings, "{}")
        kept = [self.link.with_name(".work-verifier.md.addystack-tmp"),
                self.settings.with_name(f".{self.settings.name}.addystack-tmp")]
        for path in kept:
            self.write(path, "mine\n")
        self.ok("install")
        self.assertEqual(os.readlink(self.link), str(self.source))
        self.assertEqual([path.read_text() for path in kept], ["mine\n", "mine\n"])
        self.assertEqual(sorted(p.name for p in self.link.parent.iterdir()), sorted([self.link.name, kept[0].name]))

    def test_a_failed_write_or_link_leaves_no_temporary_file(self):
        # Renaming a file or link over a non-empty folder fails after the partial exists.
        folder = pathlib.Path(self.home, "target")
        self.write(folder / "kept", "mine\n")
        for replace in (lambda: reconcile._replace(folder, "text\n"), lambda: reconcile._link(folder, self.source)):
            with self.assertRaises(OSError):
                replace()
            self.assertEqual(sorted(p.name for p in self.home.iterdir() if "addystack-tmp" in p.name), [])
        self.assertEqual((folder / "kept").read_text(), "mine\n")

    def test_leaves_a_regular_file_and_reports_it(self):
        self.write(self.link, "my own agent\n")
        result = self.cli("install")
        self.assertIn(f"left {self.link} (agent)\n  a file addystack didn't link, left as is; move it aside",
                      result.stdout)
        self.assertFalse(self.link.is_symlink())
        self.assertEqual(self.link.read_text(), "my own agent\n")
        # Install still builds, and its doctor run names the file.
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL  agent: ~/.claude/agents/work-verifier.md isn't the work-verifier agent", result.stdout)
        self.assertTrue(self.claude_md.read_text().startswith("<!-- Built by addystack build"))

    def test_a_verify_work_without_the_agent_links_nothing_and_says_how_to_install_it(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.write(self.home / ".claude/skills/verify-work/SKILL.md", (SKILLS["verify-work"] / "SKILL.md").read_text())
        out = self.cli("install").stdout
        self.assertIn(f"left {self.link} (agent)\n  not linked: verify-work has no ~/.claude/skills/verify-work/agents/"
                      "work-verifier.md; run npx skills add <the addystack repo> -g -y --skill verify-work", out)
        self.assertFalse(os.path.lexists(self.link))

    def test_without_verify_work_for_claude_nothing_needs_the_agent(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.assertNotIn("(agent)", self.ok("install").stdout)
        self.assertFalse(os.path.lexists(self.link))

    def test_a_disabled_claude_host_touches_nothing(self):
        self.write(self.config, '{ "hosts": { "claude": false } }')
        self.ok("install")
        self.assertFalse(os.path.lexists(self.link))
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/old/kit/agents/work-verifier.md")
        self.assertNotIn("(agent)", self.ok("install").stdout)
        self.assertEqual(os.readlink(self.link), "/old/kit/agents/work-verifier.md")

    def test_dry_run_previews_the_link_and_writes_nothing(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/old/kit/agents/work-verifier.md")
        before = self.snapshot()
        out = self.ok("install", "--dry-run").stdout
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"would change {self.link} (agent)", out)
        self.link.unlink()
        self.write(self.link, "my own agent\n")
        self.assertIn(f"would leave {self.link} (agent)", self.ok("install", "--dry-run").stdout)


class Command(Home):
    """While cleanest-ask or cleanest-ask-impl is enabled for Claude Code, install links
    ~/.claude/commands/cleanest.md, the command they send, to the kit's copy, and removes that
    link once both are off."""

    def setUp(self):
        super().setUp()
        self.link = self.home / ".claude/commands/cleanest.md"
        self.source = KIT / "commands/cleanest.md"

    def enable(self, on=True, ids=("cleanest-ask",)):
        self.write(self.config, json.dumps({"hooks": {"preset": "all", "enable": list(ids) if on else []}}))

    def test_off_by_default_links_nothing(self):
        self.assertNotIn("(command)", self.ok("install").stdout)
        self.assertFalse(os.path.lexists(self.link))

    def test_links_it_while_enabled_and_removes_it_once_off(self):
        self.enable()
        self.assertIn(f"changed {self.link} (command)\n  links it to", self.ok("install").stdout)
        self.assertEqual(os.readlink(self.link), str(self.source))
        self.assertIn("disable-model-invocation: true", self.link.read_text())
        self.assertNotIn("(command)", self.ok("install").stdout)
        self.enable(False)
        self.assertIn(f"changed {self.link} (command)\n  removes it: cleanest-ask and cleanest-ask-impl are off",
                      self.ok("install").stdout)
        self.assertFalse(os.path.lexists(self.link))

    def test_keeps_it_while_either_id_is_enabled(self):
        for ids in (("cleanest-ask-impl",), ("cleanest-ask", "cleanest-ask-impl")):
            with self.subTest(ids=ids):
                self.enable(ids=ids)
                self.ok("install")
                self.assertEqual(os.readlink(self.link), str(self.source))
        self.enable(ids=("cleanest-ask-impl",))
        self.assertNotIn("(command)", self.ok("install").stdout)
        self.assertEqual(os.readlink(self.link), str(self.source))

    def test_removes_a_link_to_the_kit_copy_from_before_the_checkout_moved(self):
        self.write(self.state / "resolved.json", json.dumps({"kit": "/previous/addystack"}))
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/previous/addystack/commands/cleanest.md")
        self.enable(False)
        self.assertIn(f"changed {self.link} (command)\n  removes it: cleanest-ask and cleanest-ask-impl are off",
                      self.ok("install").stdout)
        self.assertFalse(os.path.lexists(self.link))

    def test_leaves_a_users_own_file_and_link(self):
        self.write(self.link, "my own command\n")
        self.enable()
        self.assertIn(f"left {self.link} (command)", self.cli("install").stdout)
        self.assertEqual(self.link.read_text(), "my own command\n")
        self.link.unlink()
        self.link.symlink_to("/my/commands/cleanest.md")
        self.enable(False)
        self.assertNotIn("(command)", self.ok("install").stdout)
        self.assertEqual(os.readlink(self.link), "/my/commands/cleanest.md")

    def test_dry_run_previews_the_link_and_writes_nothing(self):
        self.enable()
        before = self.snapshot()
        self.assertIn(f"would change {self.link} (command)", self.ok("install", "--dry-run").stdout)
        self.assertEqual(self.snapshot(), before)


class SkillLinks(Home):
    """Install removes both hosts' links to a skill the kit's checkout dropped, as a
    maintainer's linked checkout leaves them after a pull, and leaves unrelated links."""

    def setUp(self):
        super().setUp()
        self.claude, self.agents = self.home / ".claude/skills", self.home / ".agents/skills"

    def drop(self, name, target):
        """Links name as a maintainer does: the skills CLI's folder at target, and Claude Code's
        folder through it."""
        (self.agents / name).symlink_to(target)
        (self.claude / name).symlink_to(f"../../.agents/skills/{name}")

    def test_removes_both_links_to_a_dropped_skill_and_a_second_install_changes_none(self):
        gone = KIT.parent / "dropped"
        self.drop("dropped", gone)
        out = self.ok("install").stdout
        for link in (self.claude / "dropped", self.agents / "dropped"):
            self.assertIn(f"changed {link} (skill-link)\n  removes it: the kit has no dropped skill at", out)
            self.assertFalse(os.path.lexists(link))
        self.assertNotIn("(skill-link)", self.ok("install").stdout)

    def test_removes_a_link_to_a_folder_only_untracked_files_keep_in_the_checkout_the_last_build_recorded(self):
        old = self.home / "old/skills"
        (old / "primitive/dropped/scripts/__pycache__").mkdir(parents=True)
        self.write(self.state / "resolved.json", json.dumps({"kit": str(old / "primitive/addystack")}))
        self.drop("dropped", old / "primitive/dropped")
        self.ok("install")
        self.assertFalse(os.path.lexists(self.claude / "dropped"))
        self.assertFalse(os.path.lexists(self.agents / "dropped"))

    def test_leaves_a_kit_skill_and_a_users_link(self):
        # A kit skill linked at an old layer's path is the kit's still, not install's to drop.
        (self.claude / "correct").unlink()
        (self.claude / "correct").symlink_to(KIT.parents[1] / "optional/correct")
        (self.claude / "mine").symlink_to(self.home / "my-skills/gone")
        self.assertNotIn("(skill-link)", self.cli("install").stdout)
        for link in (self.claude / "correct", self.claude / "mine"):
            self.assertTrue(link.is_symlink(), link)

    def test_a_disabled_hosts_link_goes_too_so_none_is_left_through_a_removed_one(self):
        self.drop("dropped", KIT.parent / "dropped")
        self.write(self.config, json.dumps({"hosts": {"claude": False}}))
        self.ok("install")
        self.assertFalse(os.path.lexists(self.claude / "dropped"))
        self.assertFalse(os.path.lexists(self.agents / "dropped"))

    def test_a_claude_skill_folder_naming_the_shared_one_in_another_case_removes_the_link_once(self):
        if not (self.home / ".AGENTS").exists():
            self.skipTest("the file system tells case apart")
        other = self.home / "custom-claude"
        other.mkdir()
        (other / "skills").symlink_to("../.AGENTS/skills")
        self.env["CLAUDE_CONFIG_DIR"] = str(other)
        (self.agents / "dropped").symlink_to(KIT.parent / "dropped")
        self.assertEqual(self.ok("install").stdout.count("(skill-link)"), 1)
        self.assertFalse(os.path.lexists(self.agents / "dropped"))

    def test_a_claude_skill_folder_that_links_to_the_shared_one_removes_the_link_once(self):
        shutil.rmtree(self.claude)
        self.claude.symlink_to("../.agents/skills")
        (self.agents / "dropped").symlink_to(KIT.parent / "dropped")
        out = self.ok("install").stdout
        self.assertEqual(out.count("(skill-link)"), 1, out)
        self.assertFalse(os.path.lexists(self.agents / "dropped"))

    def removes_in_another_case(self, target, bin_):
        if not (self.home / ".AGENTS").exists():
            self.skipTest("the file system tells case apart")
        self.drop("dropped", target)
        self.assertIn("(skill-link)", self.ok("install", bin_=bin_).stdout)
        self.assertFalse(os.path.lexists(self.claude / "dropped"))
        self.assertFalse(os.path.lexists(self.agents / "dropped"))

    def test_a_link_into_the_checkout_spelled_in_another_case_still_counts(self):
        self.removes_in_another_case(Path(str(KIT.parent / "dropped").replace("/skills/", "/SKILLS/")), BIN)

    def test_a_kit_run_from_a_path_spelled_in_another_case_still_finds_its_checkout(self):
        cased_bin = Path(str(BIN).replace("/skills/primitive/", "/SKILLS/primitive/"))
        self.removes_in_another_case(KIT.parent / "dropped", cased_bin)

    def test_dry_run_previews_the_removal_and_writes_nothing(self):
        self.drop("dropped", KIT.parent / "dropped")
        before = self.snapshot()
        self.assertIn(f"would change {self.claude / 'dropped'} (skill-link)", self.ok("install", "--dry-run").stdout)
        self.assertEqual(self.snapshot(), before)

class RenamedSkill(Home):
    """A linked checkout's update renames a skill's folder; install moves the dangling link."""

    def test_moves_a_dangling_link_to_the_renamed_folder_and_leaves_a_taken_name(self):
        kit_skills = self.home / "checkout/skills/primitive"
        (kit_skills / "review-code").mkdir(parents=True)
        (kit_skills / "review-code/SKILL.md").write_text("---\nname: review-code\n---\n")
        folder = self.home / ".claude/skills"
        # The home installs every core skill; this user has only the old link.
        if os.path.lexists(folder / "review-code"):
            (folder / "review-code").unlink() if (folder / "review-code").is_symlink() else shutil.rmtree(folder / "review-code")
        old = folder / "review-teammate-pr"
        old.symlink_to(kit_skills / "review-teammate-pr")
        out = self.ok("install").stdout
        self.assertIn("review-teammate-pr is review-code now: links review-code to", out)
        self.assertFalse(os.path.lexists(old))
        self.assertEqual((folder / "review-code").resolve(), (kit_skills / "review-code").resolve())
        # Once moved, a second install has nothing to do; a taken new name leaves the old link.
        self.assertNotIn("renamed-skill", self.ok("install").stdout)
        old.symlink_to(kit_skills / "review-teammate-pr")
        self.assertIn("dangles, and review-code is installed already", self.ok("install").stdout)
        self.assertTrue(old.is_symlink())

    def test_a_link_into_the_kits_own_checkout_is_moved_once_not_also_dropped(self):
        # Main's skill-link planner sees links into the kit's own tree; a renamed skill is this one's.
        claude, agents = self.home / ".claude/skills", self.home / ".agents/skills"
        for folder in (claude, agents):
            if os.path.lexists(folder / "review-code"):
                (folder / "review-code").unlink() if (folder / "review-code").is_symlink() else shutil.rmtree(folder / "review-code")
        (agents / "review-teammate-pr").symlink_to(KIT.parent / "review-teammate-pr")
        (claude / "review-teammate-pr").symlink_to("../../.agents/skills/review-teammate-pr")
        out = self.ok("install").stdout
        self.assertNotIn("(skill-link)", out)
        for folder in (claude, agents):
            self.assertEqual((folder / "review-code").resolve(), (KIT.parent / "review-code").resolve(), folder)
            self.assertFalse(os.path.lexists(folder / "review-teammate-pr"), folder)

    def test_a_link_to_an_old_folder_only_ignored_files_keep_is_moved_too(self):
        # A rename leaves untracked files behind, such as verdicts.py's __pycache__.
        kit_skills = self.home / "checkout/skills/primitive"
        (kit_skills / "review-code").mkdir(parents=True)
        (kit_skills / "review-code/SKILL.md").write_text("---\nname: review-code\n---\n")
        (kit_skills / "review-teammate-pr/scripts/__pycache__").mkdir(parents=True)
        (kit_skills / "review-teammate-pr/scripts/__pycache__/evidence.cpython-315.pyc").write_bytes(b"")
        claude, agents = self.home / ".claude/skills", self.home / ".agents/skills"
        for folder in (claude, agents):
            if os.path.lexists(folder / "review-code"):
                (folder / "review-code").unlink() if (folder / "review-code").is_symlink() else shutil.rmtree(folder / "review-code")
        (agents / "review-teammate-pr").symlink_to(kit_skills / "review-teammate-pr")
        (claude / "review-teammate-pr").symlink_to(agents / "review-teammate-pr")
        self.ok("install")
        for folder in (claude, agents):
            self.assertEqual((folder / "review-code").resolve(), (kit_skills / "review-code").resolve(), folder)
            self.assertFalse(os.path.lexists(folder / "review-teammate-pr"), folder)

    def test_moves_a_chain_of_host_links_in_one_install(self):
        kit_skills = self.home / "checkout/skills/primitive"
        (kit_skills / "review-code").mkdir(parents=True)
        (kit_skills / "review-code/SKILL.md").write_text("---\nname: review-code\n---\n")
        claude, agents = self.home / ".claude/skills", self.home / ".agents/skills"
        for folder in (claude, agents):
            folder.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(folder / "review-code"):
                (folder / "review-code").unlink() if (folder / "review-code").is_symlink() else shutil.rmtree(folder / "review-code")
        (agents / "review-teammate-pr").symlink_to(kit_skills / "review-teammate-pr")
        (claude / "review-teammate-pr").symlink_to(agents / "review-teammate-pr")
        self.ok("install")
        self.assertEqual((claude / "review-code").resolve(), (kit_skills / "review-code").resolve())
        self.assertFalse(os.path.lexists(claude / "review-teammate-pr"))
        self.assertFalse(os.path.lexists(agents / "review-teammate-pr"))

    def test_a_chain_goes_to_the_renamed_checkout_folder_never_to_another_skill(self):
        kit_skills = self.home / "checkout/skills/primitive"
        (kit_skills / "review-code").mkdir(parents=True)
        (kit_skills / "review-code/SKILL.md").write_text("kit\n")
        claude, agents = self.home / ".claude/skills", self.home / ".agents/skills"
        for folder in (claude, agents):
            folder.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(folder / "review-code"):
                (folder / "review-code").unlink() if (folder / "review-code").is_symlink() else shutil.rmtree(folder / "review-code")
        foreign = self.home / "foreign/review-code"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("foreign\n")
        (agents / "review-code").symlink_to(foreign)
        (agents / "review-teammate-pr").symlink_to(kit_skills / "review-teammate-pr")
        (claude / "review-teammate-pr").symlink_to(agents / "review-teammate-pr")
        self.ok("install")
        self.assertEqual((claude / "review-code" / "SKILL.md").read_text(), "kit\n")
        self.assertEqual((agents / "review-code" / "SKILL.md").read_text(), "foreign\n")


class ClaudeConfigDir(Home):
    """With CLAUDE_CONFIG_DIR set, Claude Code and the skills CLI use that folder, so
    install writes Claude Code's hooks, agent link, and CLAUDE.md there; unset or blank,
    ~/.claude."""
    linked = False

    def setUp(self):
        super().setUp()
        self.folder = self.home / "claude-config"
        self.env["CLAUDE_CONFIG_DIR"] = str(self.folder)
        for skills in (self.folder / "skills", self.home / ".agents/skills"):
            skills.mkdir(parents=True)
            for name, path in SKILLS.items():
                (skills / name).symlink_to(path)

    def test_install_writes_claude_codes_files_in_the_folder_it_names(self):
        out = self.ok("install").stdout
        self.assertTrue(self.commands(self.folder / "settings.json"))
        link = self.folder / "agents/work-verifier.md"
        self.assertEqual(os.readlink(link), str(self.folder / "skills/verify-work/agents/work-verifier.md"))
        self.assertTrue((self.folder / "CLAUDE.md").read_text().startswith("<!-- Built by addystack build"))
        self.assertFalse((self.home / ".claude").exists())
        # Install's doctor run checked the skill folder, the agent, and the hooks there.
        self.assertIn("ok    agent: ~/claude-config/agents/work-verifier.md is the work-verifier agent", out)
        self.assertIn("ok    hooks: match the selection", out)

    def test_doctor_checks_the_folder_it_names(self):
        self.ok("install")
        (self.folder / "skills/build").unlink()
        (self.folder / "skills/build").symlink_to(self.home / "gone")
        (self.folder / "agents/work-verifier.md").unlink()
        out = self.cli("doctor").stdout
        self.assertIn("FAIL  skill links: ~/claude-config/skills/build is a dangling link", out)
        self.assertIn("FAIL  agent: ~/claude-config/agents/work-verifier.md is missing", out)

    def test_unset_or_blank_uses_dot_claude(self):
        for name, value in {"unset": None, "blank": "  "}.items():
            with self.subTest(name):
                shutil.rmtree(self.home / ".claude", ignore_errors=True)
                self.env.pop("CLAUDE_CONFIG_DIR", None)
                if value is not None:
                    self.env["CLAUDE_CONFIG_DIR"] = value
                # Claude Code's skill folder is ~/.claude/skills now.
                (self.home / ".claude").mkdir()
                (self.folder / "skills").rename(self.home / ".claude/skills")
                self.ok("install")
                self.assertTrue(self.commands(self.settings))
                self.assertTrue((self.home / ".claude/agents/work-verifier.md").is_symlink())
                self.assertTrue(self.claude_md.is_file())
                self.assertFalse((self.folder / "settings.json").exists())
                (self.home / ".claude/skills").rename(self.folder / "skills")


class DryRun(Home):
    def test_prints_every_change_and_writes_nothing(self):
        self.write(self.config, '{ "identity": { "name": "Sam" } }')
        self.write(self.settings, json.dumps({"hooks": {"PreToolUse": [UNRELATED]}}))
        self.write(self.claude_md, "My rules.\n")
        before = self.snapshot()
        out = self.ok("install", "--dry-run").stdout
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"would change {self.settings} (hooks)", out)
        self.assertIn(f"+ PreToolUse {KIT}/hooks/", out)
        self.assertIn(f"would change {self.config.parent / 'global.md'} (adopt-instructions)", out)
        self.assertIn(f"would change {self.config} (adopt-instructions)", out)
        self.assertIn("addystack build would write", out)


    def test_previews_the_build_from_the_state_the_install_would_leave(self):
        # The adopted text lands in global.md, and the config, when there is one, names it,
        # so the built CLAUDE.md keeps the rule: the preview mustn't show it removed.
        for name, config in {"config": '{ "hosts": { "codex": false } }', "no config": None}.items():
            with self.subTest(name):
                if config is None:
                    self.config.unlink()
                else:
                    self.write(self.config, config)
                self.write(self.claude_md, "# Personal\n\nUNIQUE PREVIEW RULE\n")
                before = self.snapshot()
                out = self.ok("install", "--dry-run").stdout
                self.assertEqual(self.snapshot(), before)
                self.assertNotIn("-UNIQUE PREVIEW RULE", out.splitlines())
                self.assertIn(f"+++ {self.claude_md}", out)



class FreshUser(Home):
    """Plan check 9's local part: a user with their own CLAUDE.md, AGENTS.md, and hook
    installs the core skills the way the skills CLI does, then runs install, init --yes,
    build, and doctor. The Linux container and GitHub repo run is a later step."""
    linked = False

    def test_install_init_build_doctor(self):
        self.write(self.claude_md, "# My Claude rules\n\n- Answer in French.\n")
        self.write(self.codex_md, "# My Codex rules\n\n- Run tests first.\n")
        self.write(self.settings, json.dumps({"hooks": {"PreToolUse": [UNRELATED]}}))
        release = json.loads((KIT / "core/skills.json").read_text())["skills"]
        for name in (name for name, layer in release.items() if layer in ("primitive", "orchestrator")):
            shutil.copytree(SKILLS[name], self.home / ".agents/skills" / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
            (self.home / ".claude/skills").mkdir(parents=True, exist_ok=True)
            (self.home / ".claude/skills" / name).symlink_to(f"../../.agents/skills/{name}")

        self.ok("install")
        self.ok("init", "--yes")
        self.ok("build")
        doctor = self.ok("doctor").stdout

        self.assertNotIn("FAIL", doctor)
        global_md = (self.config.parent / "global.md").read_text()
        self.assertIn("- Answer in French.", global_md)
        self.assertIn("- Run tests first.", global_md)
        self.assertIn("- Answer in French.", self.claude_md.read_text())
        self.assertIn("- Run tests first.", self.codex_md.read_text())
        self.assertEqual(self.json(self.settings)["hooks"]["PreToolUse"][0], UNRELATED)
        for path in (self.settings, self.codex_hooks):
            ours = [c for commands in self.commands(path).values() for c in commands if c != "~/bin/my-guard.sh"]
            self.assertTrue(ours)
            for command in ours:
                self.assertTrue(command.startswith(f"{KIT}/hooks/"), command)
                self.assertTrue(pathlib.Path(command.split()[0]).is_file(), command)



@unittest.skipUnless(sys.platform == "darwin", "the guard is macOS-only")
class Guard(Home):
    """On macOS, while agent-memory-guard-notice is selected, install writes the guard's
    launchd plist, starts it, records it in the ledger, and makes sure a new agent shell
    gets a process limit; once deselected, it stops only a guard it recorded. launchctl is
    Home's stub; the limit is probed with the real zsh in the scratch HOME."""

    def setUp(self):
        super().setUp()
        self.plist = self.home / "Library/LaunchAgents/addystack.agent-memory-guard.plist"
        self.zshenv = self.home / ".zshenv"
        self.loaded = self.home / "launchctl.loaded"

    def select(self, on=True, preset="all"):
        hooks = {"preset": preset} if on else {"preset": preset, "disable": ["agent-memory-guard-notice"]}
        self.write(self.config, json.dumps({"hooks": hooks}))

    def calls(self):
        return self.launchctl_log.read_text().splitlines() if self.launchctl_log.exists() else []

    def starts(self, since=0):
        return [c for c in self.calls()[since:] if c.startswith(("bootstrap", "bootout"))]

    def doctor_line(self, out):
        return next(line for line in out.splitlines() if "memory guard:" in line)

    def test_installs_and_starts_it_then_a_second_install_changes_nothing(self):
        self.select()
        out = self.ok("install").stdout
        self.assertIn(f"changed {self.plist} (guard)", out)
        self.assertIn(f"{KIT}/hooks/agent_memory_guard.py", self.plist.read_text())
        self.assertTrue(self.loaded.exists())
        self.assertIn("ulimit -Su 3000", self.zshenv.read_text())
        self.assertIn("ok    memory guard: loaded, and agent shells capped at 3,000 processes", out)
        before = len(self.calls())
        again = self.ok("install").stdout
        self.assertNotIn("(guard)", again)
        self.assertNotIn("(shell-limit)", again)
        self.assertFalse(self.starts(before))

    def test_updates_and_restarts_a_stale_plist(self):
        self.select()
        self.ok("install")
        self.plist.write_text(self.plist.read_text().replace("agent_memory_guard.py", "old.py"))
        self.assertIn("differs from the kit's", self.cli("doctor").stdout)
        before = len(self.calls())
        self.assertIn("updates the agent memory guard's launchd plist and starts it", self.ok("install").stdout)
        self.assertIn("agent_memory_guard.py", self.plist.read_text())
        self.assertTrue(self.starts(before)[-1].startswith("bootstrap"))

    def test_restarts_a_guard_that_isnt_loaded(self):
        self.select()
        self.ok("install")
        self.loaded.unlink()
        self.assertIn("the agent memory guard isn't loaded", self.cli("doctor").stdout)
        self.assertIn("(guard)\n  starts the agent memory guard, which isn't loaded", self.ok("install").stdout)

    def test_doctor_fails_while_the_plist_is_missing(self):
        self.select()
        self.ok("install")
        self.plist.unlink()
        result = self.cli("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is missing", self.doctor_line(result.stdout))

    def test_stops_and_removes_it_once_deselected_and_keeps_the_limit(self):
        self.select()
        self.ok("install")
        self.select(False)
        out = self.ok("install").stdout
        self.assertIn("stops the agent memory guard and removes its plist", out)
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.loaded.exists())
        self.assertIn("ulimit -Su 3000", self.zshenv.read_text())
        self.assertIn("ok    memory guard: not needed", out)
        self.assertNotIn('"guard"', (self.state / "installed.json").read_text())

    def test_deselected_stops_its_guard_even_when_the_plist_is_gone(self):
        self.select()
        self.ok("install")
        self.plist.unlink()
        self.select(False)
        self.ok("install")
        self.assertFalse(self.loaded.exists())

    def test_a_stop_launchd_refuses_fails_and_the_next_install_retries(self):
        self.select()
        self.ok("install")
        self.stub("launchctl", f'echo "$*" >> {self.launchctl_log}\ncase $1 in bootout) exit 5 ;; '
                  f'print) test -f {self.loaded} ;; esac')
        self.select(False)
        self.assertNotEqual(self.cli("install").returncode, 0)
        self.assertTrue(self.plist.exists())
        before = len(self.calls())
        self.assertNotEqual(self.cli("install").returncode, 0)
        self.assertTrue(self.starts(before))

    def test_leaves_a_guard_the_user_installed_by_hand(self):
        # The README's manual steps installed it under the same label, on any preset.
        self.write(self.plist, "<plist/>")
        self.loaded.touch()
        self.select(preset="recommended")
        out = self.ok("install").stdout
        self.assertNotIn("(guard)", out)
        self.assertTrue(self.plist.exists())
        self.assertTrue(self.loaded.exists())

    def test_keeps_a_users_own_lower_limit(self):
        self.select()
        self.write(self.zshenv, "export EDITOR=vim\nulimit -Su 2000")
        self.ok("install")
        self.assertEqual(self.zshenv.read_text(), "export EDITOR=vim\nulimit -Su 2000")

    def test_a_limit_inside_an_alias_doesnt_count(self):
        self.select()
        self.write(self.zshenv, "alias cap='ulimit -Su 2000'\n")
        self.ok("install")
        self.assertTrue(self.zshenv.read_text().startswith("alias cap='ulimit -Su 2000'\n# addystack:"))
        self.assertIn("capped at 3,000", self.doctor_line(self.ok("doctor").stdout))

    def test_the_limit_works_under_nounset(self):
        self.select()
        self.write(self.zshenv, "setopt nounset\n")
        self.ok("install")
        self.assertIn("capped at 3,000", self.doctor_line(self.ok("doctor").stdout))

    def test_doctor_reports_a_limit_an_early_return_skips_and_install_adds_it_once(self):
        self.select()
        self.write(self.zshenv, "return\n")
        result = self.cli("install")
        self.assertIn("a new agent shell gets no process limit", self.doctor_line(result.stdout))
        self.cli("install")
        self.assertEqual(self.zshenv.read_text().count("ulimit -Su 3000"), 1)

    def test_an_unreadable_zshenv_stops_before_any_write(self):
        self.select()
        self.write(self.zshenv, "export EDITOR=vim\n").chmod(0)
        self.addCleanup(self.zshenv.chmod, 0o644)
        result = self.cli("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("can't read", result.stderr)
        self.zshenv.chmod(0o644)
        self.assertEqual(self.zshenv.read_text(), "export EDITOR=vim\n")
        self.assertFalse(self.plist.exists())

    def probe(self, variable):
        """A new zsh's soft limit when only variable marks it as an agent's."""
        import resource, subprocess
        env = {k: v for k, v in self.env.items() if k not in ("CLAUDECODE", "T3CODE_CLI_PATH", "T3CODE_THREAD_ID")}
        env[variable] = "1"
        hard = resource.getrlimit(resource.RLIMIT_NPROC)[1]
        done = subprocess.run(["zsh", "-c", "ulimit -Su"], env=env, capture_output=True, text=True,
                              preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NPROC, (hard, hard)))
        return done.stdout.strip().splitlines()[-1]

    def test_a_failed_restart_removes_the_new_plist_so_the_next_install_retries(self):
        self.select()
        self.ok("install")
        self.plist.write_text(self.plist.read_text().replace("agent_memory_guard.py", "old.py"))
        self.stub("launchctl", f'echo "$*" >> {self.launchctl_log}\ncase $1 in bootout|bootstrap) exit 5 ;; '
                  f'print) test -f {self.loaded} ;; esac')
        self.assertNotEqual(self.cli("install").returncode, 0)
        self.assertFalse(self.plist.exists())
        before = len(self.calls())
        self.assertNotEqual(self.cli("install").returncode, 0)
        self.assertTrue(any(c.startswith("bootstrap") for c in self.calls()[before:]))

    def test_deselecting_keeps_ownership_while_launchctl_cant_answer(self):
        self.select()
        self.ok("install")
        self.env["ADDYSTACK_LAUNCHCTL"] = str(self.home / "no-such-launchctl")  # can't run
        self.select(False)
        self.assertNotEqual(self.cli("install").returncode, 0)
        self.assertIn('"guard": true', (self.state / "installed.json").read_text())

    def test_startup_output_doesnt_hide_a_users_limit(self):
        self.select()
        self.write(self.zshenv, "echo welcome\nulimit -Su 2000\n")
        out = self.ok("install").stdout
        self.assertEqual(self.zshenv.read_text(), "echo welcome\nulimit -Su 2000\n")
        self.assertIn("capped at 2,000", self.doctor_line(out))

    def test_the_limit_never_raises_a_shells_lower_one(self):
        self.select()
        self.write(self.zshenv, "[[ -n ${CLAUDECODE-} ]] && ulimit -Su 2000\n")
        self.ok("install")
        self.assertEqual(self.probe("CLAUDECODE"), "2000")
        self.assertEqual(self.probe("T3CODE_THREAD_ID"), "3000")

    def test_dry_run_writes_and_starts_nothing(self):
        self.select()
        before = self.snapshot()
        self.assertIn("would change", self.ok("install", "--dry-run").stdout)
        self.assertEqual({k: v for k, v in self.snapshot().items() if k != self.launchctl_log},
                         {k: v for k, v in before.items() if k != self.launchctl_log})
        self.assertFalse(self.starts())


if __name__ == "__main__":
    unittest.main()

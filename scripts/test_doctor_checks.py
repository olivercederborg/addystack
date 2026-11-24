"""Tests for doctor's hosts, skill links, agent, hooks, and policy tools checks in a scratch HOME:
each passes on a working install and fails with a fix line naming what to run."""
from __future__ import annotations

import json, os, shutil, sys, unittest

from addystack_home import KIT, SKILLS, Home

GH_STACK_RULE = '{ "policy": { "repos": [ { "match": { "remote": "acme" }, "pushVia": "gh-stack" } ] } }'


class Doctor(Home):
    def check(self, name):
        """doctor's line for a check, and its fix line when it has one."""
        lines = self.cli("doctor").stdout.splitlines()
        index = next(i for i, line in enumerate(lines) if line[6:].startswith(f"{name}: "))
        fix = lines[index + 1].strip() if index + 1 < len(lines) and lines[index + 1].startswith("      fix:") else None
        return lines[index], fix

    def only_stubs_on_path(self):
        self.env["PATH"] = os.pathsep.join([str(self.stubs), "/usr/bin", "/bin"])


class Hosts(Doctor):
    def test_each_enabled_host_with_its_version(self):
        self.assertEqual(self.check("hosts"), ("ok    hosts: claude 1.2.3, codex 1.2.3", None))

    def test_an_enabled_host_missing_from_path_fails(self):
        (self.stubs / "codex").unlink()
        self.only_stubs_on_path()
        line, fix = self.check("hosts")
        self.assertTrue(line.startswith("FAIL  hosts: codex is enabled but not on PATH"), line)
        self.assertEqual(fix, "fix: install codex, or set hosts.codex to false in ~/.config/addystack/addystack.jsonc")

    def test_a_disabled_host_isnt_checked(self):
        (self.stubs / "codex").unlink()
        self.only_stubs_on_path()
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.assertEqual(self.check("hosts"), ("ok    hosts: claude 1.2.3", None))


class SkillLinks(Doctor):
    linked = False

    def core(self):
        return [name for name, layer in json.loads((KIT / "core/skills.json").read_text())["skills"].items()
                if layer in ("primitive", "orchestrator")]

    def test_a_maintainers_linked_checkout_passes(self):
        self.link_skills()
        line, _ = self.check("skill links")
        self.assertTrue(line.startswith(f"ok    skill links: {len(self.core())} core skills"), line)

    def test_an_npx_install_passes(self):
        # The skills CLI copies into ~/.agents/skills and links Claude Code's folder to it.
        for name in self.core():
            shutil.copytree(SKILLS[name], self.home / ".agents/skills" / name)
            (self.home / ".claude/skills").mkdir(parents=True, exist_ok=True)
            (self.home / ".claude/skills" / name).symlink_to(f"../../.agents/skills/{name}")
        self.assertTrue(self.check("skill links")[0].startswith("ok    skill links"))

    def lock(self):
        # The addystack skill's source names the kit's, though more names came from another.
        theirs = {name: {"source": "someone/else"} for name in ("build", "tidy", "grounding")}
        self.write(self.home / ".local/state/skills/.skill-lock.json",
                   json.dumps({"version": 3, "skills": {"addystack": {"source": "acme/addystack"}, **theirs}}))

    def test_a_core_skill_the_user_didnt_install_is_a_note_not_a_failure(self):
        # D9 lets a user install some core skills with --skill, and update leaves a removed one removed.
        self.lock()
        self.write(self.config, '{ "hosts": { "codex": false } }')
        for name in self.core():
            if name not in ("address-review", "architect"):
                (self.home / ".claude/skills").mkdir(parents=True, exist_ok=True)
                (self.home / ".claude/skills" / name).symlink_to(SKILLS[name])
        line, fix = self.check("skill links")
        count = len(self.core())
        self.assertEqual(line, f"ok    skill links: ~/.claude/skills has {count - 2} of {count} core skills; not installed: "
                               "address-review, architect (npx skills add acme/addystack -g -y --skill "
                               "address-review architect adds them)")
        self.assertIsNone(fix)

    def test_an_installed_core_skill_missing_its_files_fails_with_the_install_command_from_the_lock(self):
        self.lock()
        self.write(self.config, '{ "hosts": { "codex": false } }')
        self.write(self.home / ".claude/skills/build/references/format.md", "left over\n")
        line, fix = self.check("skill links")
        self.assertEqual(line, "FAIL  skill links: ~/.claude/skills/build has no SKILL.md")
        self.assertEqual(fix, "fix: run npx skills add acme/addystack -g -y --skill build, or link each from your "
                              "checkout")

    def test_a_dangling_link_fails(self):
        for folder in (".claude/skills", ".agents/skills"):
            (self.home / folder).mkdir(parents=True)
            for name in self.core():
                (self.home / folder / name).symlink_to(SKILLS[name])
        (self.home / ".claude/skills/build").unlink()
        (self.home / ".claude/skills/build").symlink_to(self.home / "gone")
        line, fix = self.check("skill links")
        self.assertEqual(line, "FAIL  skill links: ~/.claude/skills/build is a dangling link")
        self.assertEqual(fix, "fix: remove each dangling link, then run npx skills add <the addystack repo> -g -y "
                              "--skill build, or link each from your checkout")


class Agent(Doctor):
    def setUp(self):
        super().setUp()
        self.link = self.home / ".claude/agents/work-verifier.md"
        self.link.parent.mkdir(parents=True)

    def test_passes_once_install_links_it(self):
        line, fix = self.check("agent")
        self.assertEqual(line, "FAIL  agent: ~/.claude/agents/work-verifier.md is missing; verify-work's fork needs it "
                               "to record a Done verdict")
        self.assertEqual(fix, "fix: addystack install")
        self.cli("install")
        self.assertEqual(self.check("agent"),
                         ("ok    agent: ~/.claude/agents/work-verifier.md is the work-verifier agent, through "
                          "~/.claude/skills/verify-work/agents/work-verifier.md", None))

    def test_a_link_to_the_old_repo_root_path_fails(self):
        self.link.symlink_to("/old/kit/agents/work-verifier.md")
        line, fix = self.check("agent")
        self.assertTrue(line.startswith("FAIL  agent: ~/.claude/agents/work-verifier.md links to "
                                        "/old/kit/agents/work-verifier.md, not ~/.claude/skills/verify-work/agents/"
                                        "work-verifier.md"), line)
        self.assertEqual(fix, "fix: addystack install")

    def test_a_link_to_an_older_copy_of_the_agent_fails(self):
        # The old repo-root copy still reads as the agent while a kit checkout keeps it.
        old = self.home / "kit/agents/work-verifier.md"
        old.parent.mkdir(parents=True)
        old.write_text((SKILLS["verify-work"] / "agents/work-verifier.md").read_text())
        self.link.symlink_to(old)
        line, fix = self.check("agent")
        self.assertTrue(line.startswith(f"FAIL  agent: ~/.claude/agents/work-verifier.md links to {old}, not "), line)
        self.assertEqual(fix, "fix: addystack install")

    def test_a_file_that_isnt_the_agent_fails_and_one_that_is_passes(self):
        self.link.write_text("---\nname: my-reviewer\n---\n")
        self.assertEqual(self.check("agent")[1], "fix: move ~/.claude/agents/work-verifier.md aside, then run "
                                                 "addystack install")
        self.link.write_text((SKILLS["verify-work"] / "agents/work-verifier.md").read_text())
        self.assertEqual(self.check("agent"),
                         ("ok    agent: ~/.claude/agents/work-verifier.md is the work-verifier agent", None))

    def test_a_verify_work_without_the_agent_fails_with_its_install_command(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.write(self.home / ".claude/skills/verify-work/SKILL.md", (SKILLS["verify-work"] / "SKILL.md").read_text())
        self.assertEqual(self.check("agent")[1], "fix: run npx skills add <the addystack repo> -g -y --skill "
                                                 "verify-work, then addystack install")

    def test_a_link_to_verify_works_missing_copy_says_the_copy_is_missing(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.write(self.home / ".claude/skills/verify-work/SKILL.md", (SKILLS["verify-work"] / "SKILL.md").read_text())
        self.link.symlink_to(self.home / ".claude/skills/verify-work/agents/work-verifier.md")
        self.assertEqual(self.check("agent"),
                         ("FAIL  agent: ~/.claude/agents/work-verifier.md links to ~/.claude/skills/verify-work/agents/"
                          "work-verifier.md, which is missing; verify-work's fork needs it to record a Done verdict",
                          "fix: run npx skills add <the addystack repo> -g -y --skill verify-work, then addystack "
                          "install"))

    def test_a_link_to_verify_works_corrupt_copy_says_to_reinstall_verify_work(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.write(self.home / ".claude/skills/verify-work/SKILL.md", (SKILLS["verify-work"] / "SKILL.md").read_text())
        self.write(self.home / ".claude/skills/verify-work/agents/work-verifier.md", "corrupt agent\n")
        self.link.symlink_to(self.home / ".claude/skills/verify-work/agents/work-verifier.md")
        self.assertEqual(self.check("agent"),
                         ("FAIL  agent: ~/.claude/agents/work-verifier.md links to ~/.claude/skills/verify-work/agents/"
                          "work-verifier.md, which isn't the work-verifier agent; verify-work's fork needs it to "
                          "record a Done verdict",
                          "fix: run npx skills add <the addystack repo> -g -y --skill verify-work, then addystack "
                          "install"))

    def test_a_file_that_differs_from_verify_works_copy_fails(self):
        self.link.write_text("---\nname: work-verifier\n---\nAn older copy.\n")
        self.assertEqual(self.check("agent"),
                         ("FAIL  agent: ~/.claude/agents/work-verifier.md differs from ~/.claude/skills/verify-work/"
                          "agents/work-verifier.md, so it's an older or edited copy; verify-work's fork needs it to "
                          "record a Done verdict",
                          "fix: move ~/.claude/agents/work-verifier.md aside, then run addystack install"))

    def test_a_copy_of_the_agent_beside_verify_work_without_its_copy_fails(self):
        self.link.write_text("---\nname: work-verifier\n---\nAn older copy.\n")
        (self.home / ".claude/skills/verify-work").unlink()
        self.write(self.home / ".claude/skills/verify-work/SKILL.md", (SKILLS["verify-work"] / "SKILL.md").read_text())
        self.assertEqual(self.check("agent")[1], "fix: move ~/.claude/agents/work-verifier.md aside, then run npx "
                                                 "skills add <the addystack repo> -g -y --skill verify-work, then "
                                                 "addystack install")

    def test_a_copy_of_the_agent_without_verify_work_needs_nothing(self):
        self.link.write_text("---\nname: work-verifier\n---\nAn older copy.\n")
        (self.home / ".claude/skills/verify-work").unlink()
        self.assertEqual(self.check("agent"), ("ok    agent: not needed: verify-work isn't in ~/.claude/skills", None))

    def test_without_verify_work_nothing_needs_the_agent(self):
        (self.home / ".claude/skills/verify-work").unlink()
        self.assertEqual(self.check("agent"), ("ok    agent: not needed: verify-work isn't in ~/.claude/skills", None))

    def test_a_disabled_claude_host_needs_none(self):
        self.write(self.config, '{ "hosts": { "claude": false } }')
        self.assertEqual(self.check("agent"), ("ok    agent: not needed: the claude host is off", None))


class Hooks(Doctor):
    def test_missing_settings_fail_until_install(self):
        line, fix = self.check("hooks")
        self.assertTrue(line.startswith("FAIL  hooks: claude: "), line)
        self.assertEqual(fix, "fix: addystack install")
        self.cli("install")
        self.assertEqual(self.check("hooks"), ("ok    hooks: match the selection", None))

    def test_a_hook_removed_by_hand_fails(self):
        self.cli("install")
        settings = self.json(self.settings)
        settings["hooks"].pop("PreToolUse")
        self.settings.write_text(json.dumps(settings))
        line, _ = self.check("hooks")
        self.assertIn(f"claude: missing PreToolUse {KIT}/hooks/", line)

    def codex_lists(self, hooks):
        """A codex stub whose app-server lists these hooks."""
        (self.stubs / "codex").write_text(f"""#!{sys.executable}
import json, sys
if sys.argv[1:] != ["app-server"]:
    sys.exit(print("1.2.3"))
hooks = json.loads({json.dumps(json.dumps(hooks))})
for line in sys.stdin:
    id_ = json.loads(line).get("id")
    if id_:
        print(json.dumps({{"id": id_, "result": {{"data": [{{"hooks": hooks, "errors": []}}]}}}}), flush=True)
""")

    def test_a_kit_hook_codex_wont_run_fails_with_the_trust_fix(self):
        # Codex review of r165: Codex keys a hook's trust and enabled state by its position,
        # so removing the entries above merge-gate and ready-gate passes both theirs.
        self.cli("install")
        source = str(self.codex_hooks.resolve())
        [(merge, ready, push)] = [[hook["command"] for group in groups for hook in group["hooks"]]
                            for event, groups in self.json(self.codex_hooks)["hooks"].items()]
        kit = {"eventName": "preToolUse", "sourcePath": source}
        self.codex_lists([{**kit, "key": "0", "command": merge, "trustStatus": "modified", "enabled": True},
                          {**kit, "key": "1", "command": ready, "trustStatus": "trusted", "enabled": False},
                          {**kit, "key": "2", "command": push, "trustStatus": "trusted", "enabled": True},
                          # The user's own hook on a kit script, disabled, and an admin's: not the kit's entries.
                          {**kit, "key": "u", "command": merge, "trustStatus": "trusted", "enabled": False,
                           "sourcePath": str(self.home / ".codex/config.toml")},
                          {**kit, "key": "m", "command": "/opt/audit", "trustStatus": "managed", "enabled": True,
                           "sourcePath": "/etc/codex/requirements.toml"}])
        self.assertEqual(self.check("hooks"), (f"FAIL  hooks: codex: PreToolUse {merge} is modified; "
                                               f"codex: PreToolUse {ready} is disabled", self.CODEX_FIX))
        # A codex that can't answer, like the version stub, leaves the check to drift alone.
        self.stub("codex", "echo 1.2.3")
        self.assertEqual(self.check("hooks"), ("ok    hooks: match the selection", None))

    def test_a_kit_hook_codex_doesnt_load_fails(self):
        # Codex review of r165: with `[features] hooks = false`, Codex lists no hooks at all.
        self.cli("install")
        self.codex_lists([])
        line, fix = self.check("hooks")
        self.assertEqual([part.rsplit("/", 1)[-1] for part in line.removeprefix("FAIL  hooks: ").split("; ")],
                         ["merge-gate.py isn't loaded", "ready-gate.py isn't loaded", "push-gate.py isn't loaded"])
        self.assertEqual(fix, self.CODEX_FIX)

    CODEX_FIX = ("fix: trust and enable each in codex's /hooks; for one that isn't loaded, check "
                 "`[features] hooks` in its config.toml and that hooks.json parses")


class PolicyTools(Doctor):
    def test_nothing_is_needed_without_a_gh_stack_rule(self):
        self.only_stubs_on_path()
        self.assertEqual(self.check("policy tools"), ("ok    policy tools: none needed", None))

    def test_a_gh_stack_rule_needs_gh(self):
        self.only_stubs_on_path()
        self.write(self.config, GH_STACK_RULE)
        line, fix = self.check("policy tools")
        self.assertEqual(line, "FAIL  policy tools: gh isn't on PATH, and a rule pushes through gh stack")
        self.assertEqual(fix, "fix: install the GitHub CLI (https://cli.github.com), then gh extension install "
                              "github/gh-stack")

    def test_a_gh_stack_rule_needs_the_extension(self):
        self.stub("gh", '[ "$1" = stack ] && exit 1; echo gh 2.0')
        self.write(self.config, GH_STACK_RULE)
        self.assertEqual(self.check("policy tools"),
                         ("FAIL  policy tools: gh stack isn't installed, and a rule pushes through gh stack",
                          "fix: gh extension install github/gh-stack"))

    def test_gh_and_the_extension_pass(self):
        self.stub("gh", "echo ok")
        self.write(self.config, GH_STACK_RULE)
        self.assertEqual(self.check("policy tools"), ("ok    policy tools: gh and gh stack", None))


if __name__ == "__main__":
    unittest.main()

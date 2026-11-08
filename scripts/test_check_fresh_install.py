"""Tests for check-fresh-install.py's checks on a finished install: a good one passes, and
each kind of damage, such as a missing agent link, is named. The full run, with npx and
the registry, is the Dagger check fresh-install."""
import importlib.util, json, os, pathlib, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-fresh-install.py"
spec = importlib.util.spec_from_file_location("check_fresh_install", SCRIPT)
fresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh)


class Checks(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = pathlib.Path(folder.name).resolve()
        fresh.fresh_home(self.home)
        self.kit = self.home / ".agents/skills/addystack"
        (self.kit / "hooks").mkdir(parents=True)
        self.hook("guard.py", "exit 0")
        self.write(".config/addystack/global.md", fresh.CLAUDE_TEXT + fresh.CODEX_TEXT)
        self.add(".claude/settings.json", "PreToolUse", "Bash", "~/.agents/skills/addystack/hooks/guard.py")
        self.add(".codex/hooks.json", "Stop", None, "~/.agents/skills/addystack/hooks/guard.py")
        self.write(".agents/skills/verify-work/agents/work-verifier.md", "---\nname: work-verifier\n---\n")
        (self.home / ".claude/skills").mkdir()
        (self.home / ".claude/skills/verify-work").symlink_to("../../.agents/skills/verify-work")
        self.agent = self.home / ".claude/agents/work-verifier.md"
        self.agent.parent.mkdir()
        self.agent.symlink_to(self.home / ".claude/skills/verify-work/agents/work-verifier.md")

    def write(self, name, text):
        (self.home / name).parent.mkdir(parents=True, exist_ok=True)
        (self.home / name).write_text(text)

    def hook(self, name, body):
        path = self.kit / "hooks" / name
        path.write_text(f"#!/bin/sh\ncat > /dev/null\n{body}\n")
        path.chmod(0o755)

    def add(self, name, event, matcher, command):
        data = json.loads((self.home / name).read_text())
        group = {"hooks": [{"type": "command", "command": command}], **({"matcher": matcher} if matcher else {})}
        data["hooks"].setdefault(event, []).append(group)
        self.write(name, json.dumps(data))

    def problems(self):
        return fresh.checks(self.home, {**os.environ, "HOME": str(self.home)}, self.kit)[0]

    def test_a_good_install_passes(self):
        self.assertEqual(self.problems(), [])

    def test_lost_instructions_and_hooks_are_named(self):
        self.write(".config/addystack/global.md", fresh.CLAUDE_TEXT)
        self.write(".codex/hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "~/.agents/skills/addystack/hooks/guard.py"}]}]}}))
        problems = self.problems()
        self.assertTrue(any("lacks the old AGENTS.md" in p for p in problems), problems)
        self.assertTrue(any("lost the user's hook my-codex-hook.sh" in p for p in problems), problems)

    def test_a_missing_or_stale_agent_link_fails(self):
        self.agent.unlink()
        self.assertTrue(any(f"{self.agent} doesn't resolve to" in p for p in self.problems()))
        self.agent.symlink_to("/old/kit/agents/work-verifier.md")
        self.assertTrue(any(f"{self.agent} doesn't resolve to" in p for p in self.problems()))

    def test_a_hook_outside_the_installed_skill_fails(self):
        self.add(".claude/settings.json", "Stop", None, "~/kit/hooks/guard.py")
        self.assertTrue(any("doesn't run a script in" in p for p in self.problems()))

    def test_a_bash_hook_that_denies_ls_fails(self):
        self.hook("guard.py", 'echo \'{"permissionDecision": "deny"}\'')
        self.assertTrue(any("on `ls` exited 0" in p for p in self.problems()))



class TreeRepo(unittest.TestCase):
    """The source the check installs from holds the kit and nothing the workshop keeps."""

    def tree(self, files):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = pathlib.Path(folder.name, "checkout")
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        return pathlib.Path(fresh.tree_repo(folder.name, root).removeprefix("file://"))

    def test_workshop_installs_only_what_kit_txt_lists(self):
        # A stand-in for the workshop's maintainer/export_kit.py, which the kit doesn't ship.
        export = ("def listed(path):\n"
                  "    lines = (line.split('#', 1)[0].strip() for line in path.read_text().splitlines())\n"
                  "    return [line for line in lines if line]\n")
        repo = self.tree({"maintainer/kit.txt": "# kit\nREADME.md\nskills/primitive  # shipped\n",
                          "maintainer/export_kit.py": export, "README.md": "kit",
                          "skills/primitive/a/SKILL.md": "a", "skills/preferences/my-inbox/SKILL.md": "c"})
        self.assertTrue((repo / "skills/primitive/a/SKILL.md").is_file())
        self.assertTrue((repo / "README.md").is_file())
        self.assertFalse((repo / "skills/preferences").exists())
        self.assertFalse((repo / "maintainer").exists())

    def test_kit_repo_installs_its_whole_tree(self):
        repo = self.tree({"README.md": "kit", "skills/primitive/a/SKILL.md": "a"})
        self.assertTrue((repo / "skills/primitive/a/SKILL.md").is_file())

if __name__ == "__main__":
    unittest.main()

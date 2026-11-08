"""Tests for lib/render.py on a neutral user: sections merge by heading in source order,
Claude's file imports the built parts while Codex's inlines them, excluded principles and
a missing taste file drop out, paths render under ~ only inside $HOME, and the core
templates still render today's router.md and principles/index.md."""
from __future__ import annotations

import os, pathlib, re, shutil, subprocess, sys, tempfile, unittest, unittest.mock

REPO = pathlib.Path(__file__).resolve().parent.parent
KIT = REPO / "skills" / "primitive" / "addystack"
sys.path[:0] = [str(KIT / "lib"), str(KIT / "hooks")]
import config, render, resolved  # noqa: E402

USER = """{
  "identity": { "name": "Sam" },
  "judgment": { "principles": { "exclude": ["slim-scope"] }, "taste": "taste.md" },
  "instructions": "global.md"
}
"""
GLOBAL = "# Actions\n\n- Sam's own action.\n\n# Sam's section\n\n- Only Sam has this.\n"


class Render(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = pathlib.Path(folder.name).resolve()
        for name, text in [("addystack.jsonc", USER), ("global.md", GLOBAL), ("taste.md", "taste")]:
            (self.dir / name).write_text(text)
        for module, name, path in [(resolved, "STATE", "state/resolved.json"), (render, "CODEX", "AGENTS.md")]:
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, self.dir / path)
        claude_md = unittest.mock.patch.dict(os.environ, {"ADDYSTACK_CLAUDE_MD": str(self.dir / "CLAUDE.md")})
        claude_md.start()
        self.addCleanup(claude_md.stop)
        self.resolved = config.resolve(self.dir / "addystack.jsonc")

    def render(self, **changes):
        return render.instructions({**self.resolved, **changes})

    def test_writes_each_host_file_and_the_parts_claude_imports(self):
        self.assertEqual(sorted(self.render()), sorted([
            self.dir / "CLAUDE.md", self.dir / "AGENTS.md",
            self.dir / "state" / "router.md", self.dir / "state" / "principles.md"]))

    def test_claude_imports_the_router_and_merges_sections_by_heading(self):
        claude = self.render()[self.dir / "CLAUDE.md"]
        lines = claude.split("\n")
        self.assertTrue(lines[0].startswith("<!-- Built by addystack build"))
        self.assertEqual(lines[1], f"@{self.dir / 'state' / 'router.md'}")
        self.assertEqual(re.findall(r"^# .*", claude, re.M),
                         ["# Evidence and execution", "# Actions", "# Specialized work", "# Sam's section"])
        actions = claude.split("# Actions\n\n")[1].split("\n\n#")[0].split("\n")
        self.assertEqual(actions[-1], "- Sam's own action.")
        self.assertIn("Bash tool's timeout", claude.split("# Actions")[0])

    def test_the_routers_policy_command_runs_from_a_kit_path_with_spaces(self):
        kit = self.dir / "kit with spaces"
        for name in ("bin", "lib", "hooks", "schema", "core"):
            shutil.copytree(KIT / name, kit / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(KIT / "addystack.defaults.jsonc", kit)
        router = self.render(kit=str(kit))[self.dir / "state" / "router.md"]
        command = re.search(r"`([^`]*) policy --repo <target>`", router).group(1)
        run = subprocess.run(f"{command} policy --repo {self.dir}", shell=True, capture_output=True, text=True,
                             env={**os.environ, "ADDYSTACK_STATE": str(self.dir / "state")})
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_the_router_part_names_the_user_and_imports_the_principles(self):
        files = self.render()
        router = files[self.dir / "state" / "router.md"]
        self.assertIn("How Sam's agents pick a workflow", router)
        self.assertIn(f"\n@{self.dir / 'state' / 'principles.md'}\n", router)
        self.assertNotIn("{{", router + files[self.dir / "state" / "principles.md"])

    def test_principles_leave_out_excluded_ones_and_name_the_taste_file(self):
        principles = self.render()[self.dir / "state" / "principles.md"]
        self.assertIn("**[prove-it-works]", principles)
        self.assertNotIn("slim-scope", principles)
        self.assertIn(f"What good code and UI look like:\n`{self.dir / 'taste.md'}`.", principles)

    def test_without_taste_the_sentence_goes(self):
        judgment = {**self.resolved["judgment"], "taste": None}
        principles = self.render(judgment=judgment)[self.dir / "state" / "principles.md"]
        self.assertIn("read its file in full from\n`", principles)
        self.assertNotIn("What good code", principles)

    def test_without_principles_the_part_and_its_import_go(self):
        judgment = {"principles": {"preset": "none", "exclude": []}, "taste": None}
        files = self.render(judgment=judgment)
        self.assertNotIn(self.dir / "state" / "principles.md", files)
        self.assertNotIn("principles.md", files[self.dir / "state" / "router.md"])
        self.assertNotIn("# Principles", files[self.dir / "AGENTS.md"])

    def test_without_principles_the_taste_line_stays(self):
        judgment = {"principles": {"preset": "none", "exclude": []}, "taste": str(self.dir / "taste.md")}
        files = self.render(judgment=judgment)
        self.assertIn(f"`{self.dir / 'taste.md'}`", files[self.dir / "state" / "principles.md"])
        self.assertIn(f"`{self.dir / 'taste.md'}`", files[self.dir / "AGENTS.md"])
        self.assertNotIn("# Principles", files[self.dir / "AGENTS.md"])

    def test_a_heading_inside_a_code_fence_stays_in_its_section(self):
        mine = self.dir / "fenced.md"
        mine.write_text("# Examples\n\nRun:\n```sh\n# Actions\necho hi\n```\n\nAfter.\n")
        agents = self.render(instructions=[str(mine)])[self.dir / "AGENTS.md"]
        example = agents[agents.index("# Examples"):]
        self.assertIn("Run:\n```sh\n# Actions\necho hi\n```\n\nAfter.", example)

    def test_an_import_line_inside_a_code_fence_stays_text(self):
        mine = self.dir / "fenced.md"
        mine.write_text("# Example\n\n```text\n@router.md\n```\n")
        files = self.render(instructions=[str(mine)])
        for host in ("AGENTS.md", "CLAUDE.md"):
            self.assertIn("```text\n@router.md\n```", files[self.dir / host])

    def test_codex_inlines_the_router_and_principles(self):
        codex = self.render()[self.dir / "AGENTS.md"]
        self.assertNotRegex(codex, r"(?m)^@")
        self.assertLess(codex.index("# Router"), codex.index("# Principles"))
        self.assertLess(codex.index("# Principles"), codex.index("## Routes"))
        self.assertLess(codex.index("## Routes"), codex.index("# Evidence and execution"))
        self.assertIn("The shell is zsh on macOS", codex)
        self.assertNotIn("Bash tool's timeout", codex)
        self.assertEqual(codex.count("- Sam's own action."), 1)

    def test_claudes_file_is_in_claude_config_dir_unless_addystack_claude_md_names_one(self):
        # Claude Code reads its user CLAUDE.md from its config folder.
        folder = self.dir / "claude-config"
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(folder)}):
            self.assertIn(self.dir / "CLAUDE.md", self.render())
            del os.environ["ADDYSTACK_CLAUDE_MD"]
            self.assertIn(folder / "CLAUDE.md", self.render())

    def test_a_disabled_host_gets_no_file(self):
        files = self.render(hosts={**self.resolved["hosts"], "codex": False})
        self.assertNotIn(self.dir / "AGENTS.md", files)
        files = self.render(hosts={**self.resolved["hosts"], "claude": False})
        self.assertEqual(list(files), [self.dir / "AGENTS.md"])

    def test_the_kit_renders_under_home_as_a_tilde_path(self):
        home = pathlib.Path.home()
        if not str(KIT).startswith(f"{home}/"):
            self.skipTest("the kit isn't under $HOME here")
        router = self.render()[self.dir / "state" / "router.md"]
        self.assertIn(f"`~/{KIT.relative_to(home)}/bin/addystack policy --repo <target>`", router)

    def test_a_kit_outside_home_renders_absolute(self):
        kit = self.dir / "kit"
        shutil.copytree(KIT / "core", kit / "core")
        router = self.render(kit=str(kit))[self.dir / "state" / "router.md"]
        self.assertIn(f"`{kit}/bin/addystack policy --repo <target>`", router)


class Templates(unittest.TestCase):
    """Until the live files switch to the build, core/ copies router.md and
    principles/index.md; rendered for the kit's maintainer, they must match."""

    @unittest.skipUnless((REPO / "router.md").is_file(), "the maintainer's live router is the workshop's")
    def test_core_renders_todays_router_and_principles(self):
        value = config.merge(config.load_layers(KIT / "missing"), KIT)
        # The live index names the maintainer and their checkout, which the render fills in.
        live = re.match(r"# Principles\n\nHow (\S+) wants work done\. .*?`(\S+)/principles/`",
                        (REPO / "principles" / "index.md").read_text(), re.S)
        name, today = live.groups()
        value["identity"]["name"] = name
        value["judgment"]["taste"] = str(pathlib.Path(today.replace("~", str(pathlib.Path.home()), 1)) / "shared/taste.md")
        parts = {path.name: text for path, text in render.instructions(value).items()}
        router = re.sub(r"(?m)^@\S+/principles\.md$", f"@{today}/principles/index.md", parts["router.md"])
        self.assertEqual(router.replace(render._home(KIT), today), (REPO / "router.md").read_text())
        principles = parts["principles.md"].replace(render._home(KIT), today)
        self.assertEqual(principles, (REPO / "principles" / "index.md").read_text())

    def test_principle_excludes_name_each_indexed_principle(self):
        schema = config.json.loads((KIT / "schema" / "v1.json").read_text())
        names = schema["properties"]["judgment"]["properties"]["principles"]["properties"]["exclude"]["items"]["enum"]
        indexed = re.findall(r"^- \*\*\[([\w-]+)\]", (KIT / "core" / "principles.md").read_text(), re.M)
        self.assertEqual(names, indexed)
        self.assertEqual(sorted(names), sorted(p.stem for p in (KIT / "principles").glob("*.md") if p.stem != "index"))


if __name__ == "__main__":
    unittest.main()

"""Tests for `addystack init` in a scratch HOME: --yes writes a valid config with the
detected defaults and $schema set (D3), an existing config is replaced only with --force,
and without --yes or a terminal it writes nothing."""
from __future__ import annotations

import json, os, re, unittest

from addystack_home import KIT, Home

SCHEMA = KIT / "schema" / "v1.json"


class Init(Home):
    def setUp(self):
        super().setUp()
        self.write(self.home / ".gitconfig", "[user]\n\tname = Sam Example\n")

    def parsed(self):
        return json.loads(re.sub(r"(?m)^\s*//.*$", "", self.config.read_text()))

    def test_yes_writes_the_detected_defaults_and_the_installed_schema(self):
        self.assertIn("next: addystack install", self.ok("init", "--yes").stdout)
        self.assertEqual(self.parsed(), {"$schema": str(SCHEMA), "version": 1, "identity": {"name": "Sam"},
                                         "hosts": {"claude": True, "codex": True, "t3": False},
                                         "checkQueue": {"maxChecks": 4}})
        self.assertIn("ok    config: valid, layers defaults, user", self.ok("install").stdout)

    def test_a_host_not_on_path_is_written_disabled(self):
        (self.stubs / "codex").unlink()
        self.env["PATH"] = os.pathsep.join([str(self.stubs), "/usr/bin", "/bin"])
        self.ok("init", "--yes")
        self.assertEqual(self.parsed()["hosts"], {"claude": True, "codex": False, "t3": False})

    def test_names_a_global_md_install_left(self):
        self.write(self.config.parent / "global.md", "# Mine\n")
        self.ok("init", "--yes")
        self.assertEqual(self.parsed()["instructions"], "global.md")

    def test_the_public_schema_url_when_it_answers(self):
        self.env["ADDYSTACK_SCHEMA_URL"] = SCHEMA.as_uri()
        self.ok("init", "--yes")
        self.assertEqual(self.parsed()["$schema"], SCHEMA.as_uri())

    def test_the_installed_schema_when_the_url_doesnt_answer(self):
        self.env["ADDYSTACK_SCHEMA_URL"] = (self.home / "missing.json").as_uri()
        self.ok("init", "--yes")
        self.assertEqual(self.parsed()["$schema"], str(SCHEMA))

    def test_refuses_to_replace_a_config_without_force(self):
        self.write(self.config, '{ "identity": { "name": "Kept" } }')
        result = self.cli("init", "--yes")
        self.assertEqual(result.returncode, 1)
        self.assertIn("pass --force", result.stderr)
        self.assertEqual(self.config.read_text(), '{ "identity": { "name": "Kept" } }')

    def test_force_replaces_it_and_keeps_the_old_one(self):
        self.write(self.config, '{ "identity": { "name": "Kept" } }')
        self.ok("init", "--yes", "--force")
        self.assertEqual(self.parsed()["identity"], {"name": "Sam"})
        self.assertEqual((self.config.parent / "addystack.jsonc.bak").read_text(), '{ "identity": { "name": "Kept" } }')

    def test_without_yes_or_a_terminal_it_writes_nothing(self):
        before = self.snapshot()
        result = self.cli("init")
        self.assertEqual(result.returncode, 2)
        self.assertIn("pass --yes", result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()

"""Tests for lib/hookset.py: every manifest entry carries an id, tags, and a {{kit}}
command; select() applies the preset's tags, then requires, then enable and disable, then
hosts, in manifest order; a config shaped like the maintainer's selects today's whole
manifest (plan check 1); turnBlock off drops routine_stop and reply_budget even under
`all` (check 7); render() groups by event and matcher; and drift() compares only the hooks
addystack installs."""
from __future__ import annotations

import json, os, pathlib, shlex, sys, tempfile, unittest, unittest.mock

KIT = pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack"
sys.path[:0] = [str(KIT / "lib"), str(KIT / "hooks")]
import config  # noqa: E402
import hookset  # noqa: E402

MANIFEST = json.loads((KIT / "hooks" / "manifest.json").read_text())
# Any file serves as replies.rules for selection; this one is in every checkout of the kit.
RULES = KIT / "SKILL.md"
TAGS = {"safety", "workflow", "replies", "machine"}


def resolve(text, kit=KIT):
    """The Resolved value of a user config, for the kit at kit."""
    with tempfile.TemporaryDirectory() as folder:
        user = pathlib.Path(folder, "addystack.jsonc")
        user.write_text(text)
        layers = config.load_layers(user)
        assert not config.validate(layers), config.validate(layers)
        return config.merge(layers, kit)


def ids(entries):
    return [entry.id for entry in entries]


def manifest_ids(runtime, tags=TAGS, host="darwin"):
    return [e["id"] for e in MANIFEST[runtime]
            if set(e["tags"]) & tags and (not e.get("hosts") or host in e["hosts"])]


class Manifest(unittest.TestCase):
    def test_each_entry_has_an_id_tags_and_a_kit_command(self):
        defaults = resolve("{}")
        for runtime, entries in MANIFEST.items():
            for entry in entries:
                with self.subTest(runtime=runtime, id=entry.get("id")):
                    self.assertRegex(entry["id"], r"^[a-z0-9-]+$")
                    self.assertTrue(entry["tags"] and set(entry["tags"]) <= TAGS)
                    script = entry["command"].split()[0]
                    self.assertTrue(script.startswith("{{kit}}/hooks/"))
                    self.assertTrue((KIT / script.removeprefix("{{kit}}/")).is_file())
                    if "requires" in entry:
                        # A path the kit's defaults hold, so it names a real Resolved key.
                        value = defaults
                        for key in entry["requires"].partition("=")[0].split("."):
                            value = value[key]

    def test_an_id_names_one_script_in_a_runtime(self):
        for runtime, entries in MANIFEST.items():
            scripts = {}
            for entry in entries:
                scripts.setdefault(entry["id"], set()).add(entry["command"].split()[0])
            for name, found in scripts.items():
                with self.subTest(runtime=runtime, id=name):
                    self.assertEqual(len(found), 1)


class Select(unittest.TestCase):
    def test_recommended_selects_the_safety_and_workflow_hooks(self):
        resolved = resolve("{}")
        for runtime in MANIFEST:
            with self.subTest(runtime=runtime):
                self.assertEqual(ids(hookset.select(resolved, runtime, "darwin")),
                                 manifest_ids(runtime, {"safety", "workflow"}))

    def test_a_config_like_the_maintainers_selects_the_whole_manifest(self):
        """Check 1's hook half: preset all with the turn block on selects every manifest
        entry, in order, with only `{{kit}}` filled in."""
        resolved = resolve(json.dumps({"hooks": {"preset": "all", "enable": ["gh-stack-only"]},
                                       "replies": {"style": "reply-shape", "rules": str(RULES),
                                                   "turnBlock": True}}))
        kit = hookset._kit(resolved)
        for runtime in MANIFEST:
            for host in ("darwin", "linux"):
                with self.subTest(runtime=runtime, host=host):
                    want = [(e["id"], e["event"], e["matcher"], e["command"].replace("{{kit}}", kit), e["timeout"],
                             e.get("onFailure")) for e in MANIFEST[runtime]
                            if not e.get("hosts") or host in e["hosts"]]
                    got = [(e.id, e.event, e.matcher, e.command, e.timeout, e.onFailure)
                           for e in hookset.select(resolved, runtime, host)]
                    self.assertEqual(got, want)

    def test_turn_block_off_drops_routine_stop_and_reply_budget(self):
        """Check 7, and an explicit enable can't bypass `requires`."""
        for enable in ([], ["routine-stop", "reply-budget"]):
            resolved = resolve(json.dumps({"hooks": {"preset": "all", "enable": enable},
                                           "replies": {"turnBlock": False}}))
            for runtime in MANIFEST:
                with self.subTest(enable=enable, runtime=runtime):
                    selected = ids(hookset.select(resolved, runtime, "darwin"))
                    self.assertNotIn("routine-stop", selected)
                    self.assertNotIn("reply-budget", selected)
                    self.assertIn("bare-references", selected)

    def test_reply_hooks_follow_their_preferences(self):
        """D11: a reply hook whose preference is off isn't selected, even when enabled."""
        cases = [({"style": "own"}, []),
                 ({"style": "reply-shape"}, ["reply-shape-context"]),
                 ({"style": "own", "rules": str(RULES)}, ["reply-rules"]),
                 ({"style": "reply-shape", "rules": str(RULES)}, ["reply-shape-context", "reply-rules"])]
        for replies, want in cases:
            resolved = resolve(json.dumps({"hooks": {"preset": "all", "enable": ["reply-shape-context", "reply-rules"]},
                                           "replies": replies}))
            for runtime in MANIFEST:
                with self.subTest(replies=replies, runtime=runtime):
                    got = [i for i in ids(hookset.select(resolved, runtime, "darwin"))
                           if i in ("reply-shape-context", "reply-rules")]
                    self.assertEqual(got, want)

    def test_enable_and_disable_by_id(self):
        resolved = resolve('{ "hooks": { "enable": ["bare-references"], "disable": ["merge-gate"] } }')
        for runtime in MANIFEST:
            with self.subTest(runtime=runtime):
                selected = ids(hookset.select(resolved, runtime, "darwin"))
                self.assertIn("bare-references", selected)
                self.assertNotIn("merge-gate", selected)
                self.assertNotIn("routine-stop", selected)

    def test_hosts_apply_last(self):
        resolved = resolve('{ "hooks": { "preset": "all" } }')
        self.assertIn("keychain-home-guard", ids(hookset.select(resolved, "claude", "darwin")))
        for host in ("linux", "sandbox"):
            self.assertNotIn("keychain-home-guard", ids(hookset.select(resolved, "claude", host)))

    def test_kit_is_under_home_absolute_elsewhere_and_quoted_when_it_must_be(self):
        with tempfile.TemporaryDirectory() as home, unittest.mock.patch.dict(os.environ, {"HOME": home}):
            inside = pathlib.Path(home, "kit")
            self.assertEqual(hookset._kit({"kit": str(inside)}), "~/kit")
            self.assertEqual(hookset._kit({"kit": "/opt/addystack"}), "/opt/addystack")
            spaced = hookset._kit({"kit": f"{home}/my kit"})
            self.assertEqual(shlex.split(f"{spaced}/hooks/x.py"), [f"{home}/my kit/hooks/x.py"])


class Render(unittest.TestCase):
    def test_groups_consecutive_matchers_within_each_event(self):
        entry = lambda id_, event, matcher: hookset.HookEntry(id_, event, matcher, f"/k/{id_}.py", 10, None)
        hooks = hookset.render([entry("a", "PreToolUse", "Bash"), entry("b", "PreToolUse", "Bash"),
                                entry("c", "PreToolUse", "Write"), entry("d", "Stop", None),
                                hookset.HookEntry("e", "PreToolUse", "Write", "/k/e.py", 60, "block")])
        self.assertEqual(hooks, {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/k/a.py", "timeout": 10},
                                                        {"type": "command", "command": "/k/b.py", "timeout": 10}]},
                           {"matcher": "Write", "hooks": [
                               {"type": "command", "command": "/k/c.py", "timeout": 10},
                               {"type": "command", "command": "/k/e.py", "timeout": 60, "onFailure": "block"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "/k/d.py", "timeout": 10}]}]})


class Merge(unittest.TestCase):
    """hookset.merge: the selected hooks replace the ones owned() names, in their place."""

    @staticmethod
    def hook(command):
        return {"type": "command", "command": command, "timeout": 10}

    def entry(self, id_, event="Stop", matcher=None):
        return hookset.HookEntry(id_, event, matcher, f"/kit/{id_}.py", 10, None)

    def merge(self, document, entries, ours=("/kit/old.py", "/kit/a.py", "/kit/b.py")):
        return hookset.merge(document, entries, lambda event, command: command in ours)

    def test_keeps_every_other_key_and_hook_in_order(self):
        mine = {"matcher": "Bash", "hooks": [self.hook("~/bin/mine.sh")]}
        merged = self.merge({"model": "opus", "hooks": {"PreToolUse": [mine]}, "env": {}},
                            [self.entry("a", "PreToolUse", "Bash"), self.entry("b")])
        self.assertEqual(list(merged), ["model", "hooks", "env"])
        self.assertEqual(merged["hooks"], {"PreToolUse": [mine, {"matcher": "Bash", "hooks": [self.hook("/kit/a.py")]}],
                                           "Stop": [{"hooks": [self.hook("/kit/b.py")]}]})

    def test_a_hook_no_longer_selected_goes_and_an_emptied_group_and_event_go_with_it(self):
        merged = self.merge({"hooks": {"Stop": [{"hooks": [self.hook("/kit/old.py")]}],
                                       "PreToolUse": [{"hooks": [self.hook("/kit/old.py"), self.hook("~/mine.sh")]}]}},
                            [])
        self.assertEqual(merged["hooks"], {"PreToolUse": [{"hooks": [self.hook("~/mine.sh")]}]})

    def test_selected_hooks_take_the_place_of_the_first_one_removed(self):
        first, last = {"hooks": [self.hook("~/first.sh")]}, {"hooks": [self.hook("~/last.sh")]}
        merged = self.merge({"hooks": {"Stop": [first, {"hooks": [self.hook("/kit/old.py")]}, last]}},
                            [self.entry("a"), self.entry("b")])
        self.assertEqual(merged["hooks"]["Stop"], [first, {"hooks": [self.hook("/kit/a.py"), self.hook("/kit/b.py")]},
                                                   last])

    def test_merging_twice_changes_nothing(self):
        once = self.merge({"hooks": {"Stop": [{"hooks": [self.hook("~/mine.sh")]}]}}, [self.entry("a")])
        self.assertEqual(self.merge(once, [self.entry("a")]), once)

    def test_a_document_without_hooks_gets_none_when_nothing_is_selected(self):
        self.assertEqual(self.merge({"model": "opus"}, []), {"model": "opus"})

    def test_owner_names_recorded_hooks_and_the_kits_but_not_a_users(self):
        resolved = resolve("{}")
        owned = hookset.owner(resolved, [("Stop", "/old/kit/hooks/x.py")])
        self.assertTrue(owned("Stop", "/old/kit/hooks/x.py"))
        self.assertFalse(owned("PreToolUse", "/old/kit/hooks/x.py"))
        self.assertTrue(owned("Stop", f"{resolved['kit']}/hooks/merge-gate.py"))
        self.assertTrue(owned("Stop", f"{hookset._kit(resolved)}/hooks/merge-gate.py"))
        self.assertTrue(owned("SessionStart", f"{resolved['kit']}/hooks/reply-shape-context.py --rules"))
        self.assertFalse(owned("Stop", "/opt/my-hooks/merge-gate.py"))

    def test_owner_names_a_retired_kit_hook_without_a_ledger_entry(self):
        # Codex review of the UI cards' removal: settings kept running the deleted reply-card.py.
        resolved = resolve("{}")
        owned = hookset.owner(resolved)
        self.assertTrue(owned("PreToolUse", f"{resolved['kit']}/hooks/reply-card.py"))
        self.assertTrue(owned("PreToolUse", f"{hookset._kit(resolved)}/hooks/reply-card.py"))
        self.assertFalse(owned("PreToolUse", "/opt/my-hooks/reply-card.py"))
        stale = {"hooks": {"PreToolUse": [{"matcher": "mcp__t3-code__html_render", "hooks": [
            {"type": "command", "command": f"{hookset._kit(resolved)}/hooks/reply-card.py", "timeout": 10}]}]}}
        merged = hookset.merge(stale, hookset.select(resolved, "claude"), owned)
        self.assertNotIn("reply-card.py", json.dumps(merged))
        self.assertFalse((KIT / "hooks" / "reply-card.py").exists())

    def test_owner_doesnt_name_a_users_hook_on_a_kit_script_no_manifest_entry_runs(self):
        resolved = resolve("{}")
        owned = hookset.owner(resolved)
        self.assertFalse(owned("PreToolUse", f"{resolved['kit']}/hooks/my-personal-hook.sh"))
        self.assertFalse(owned("Stop", f"{resolved['kit']}/hooks/merge-gate.py --my-flag"))


class Drift(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = pathlib.Path(folder.name, "settings.json")
        self.resolved = resolve('{ "hooks": { "preset": "all" }, "replies": { "turnBlock": true } }')
        self.hooks = hookset.render(hookset.select(self.resolved, "claude"))

    def drift(self):
        self.settings.write_text(json.dumps({"hooks": self.hooks}))
        return hookset.drift(self.resolved, "claude", self.settings)

    def test_the_rendered_selection_has_no_drift(self):
        self.assertEqual(self.drift(), [])

    def test_a_users_own_hook_isnt_compared(self):
        self.hooks["Stop"].append({"hooks": [{"type": "command", "command": "~/bin/my-hook.sh"}]})
        self.assertEqual(self.drift(), [])

    def test_a_users_hook_sharing_a_kit_scripts_name_isnt_compared(self):
        self.hooks["Stop"].append({"hooks": [{"type": "command", "command": "/opt/my-hooks/merge-gate.py"}]})
        self.assertEqual(self.drift(), [])

    def test_a_users_hook_on_a_kit_script_no_manifest_entry_runs_isnt_compared(self):
        self.hooks["Stop"].append({"hooks": [{"type": "command",
                                              "command": f"{self.resolved['kit']}/hooks/my-personal-hook.sh"}]})
        self.assertEqual(self.drift(), [])

    def test_a_retired_kit_hook_left_in_the_settings_is_extra(self):
        command = f"{hookset._kit(self.resolved)}/hooks/reply-card.py"
        self.hooks["PreToolUse"].append({"matcher": "mcp__t3-code__html_render",
                                         "hooks": [{"type": "command", "command": command, "timeout": 10}]})
        self.assertEqual(self.drift(), [f"claude: extra PreToolUse {command}"])

    def test_a_regular_file_in_an_older_link_folder_is_the_users(self):
        with tempfile.TemporaryDirectory() as legacy:
            mine = pathlib.Path(legacy, "merge-gate.py")
            mine.write_text("#!/bin/sh\n")
            self.hooks["Stop"].append({"hooks": [{"type": "command", "command": str(mine)}]})
            with unittest.mock.patch.object(hookset, "_legacy_dirs", lambda: (legacy,)):
                self.assertEqual(self.drift(), [])

    def test_an_older_link_to_a_kit_script_is_ours_even_under_another_name(self):
        with tempfile.TemporaryDirectory() as legacy:
            link = pathlib.Path(legacy, "session-start.sh")
            link.symlink_to(KIT / "hooks" / "reply-shape-context.py")
            self.hooks.setdefault("SessionStart", []).append({"hooks": [{"type": "command", "command": str(link)}]})
            with unittest.mock.patch.object(hookset, "_legacy_dirs", lambda: (legacy,)):
                drift = self.drift()
        self.assertEqual(drift, [f"claude: extra SessionStart {link}"])

    def test_a_missing_selected_hook_is_drift(self):
        stop = self.hooks["Stop"][0]["hooks"]
        dropped = stop.pop()
        self.assertEqual(self.drift(), [f"claude: missing Stop {dropped['command']}"])

    def test_a_hook_the_config_no_longer_selects_is_extra(self):
        self.resolved["replies"]["turnBlock"] = False
        self.assertEqual(self.drift(), [f"claude: extra Stop {hookset._kit(self.resolved)}/hooks/{name}"
                                        for name in ("routine_stop.py", "reply_budget.py")])


class ClaudeConfigDir(unittest.TestCase):
    """Claude Code's settings and the older installs' link folder are in the folder
    CLAUDE_CONFIG_DIR names, looked up on each call."""

    def test_claudes_settings_and_older_link_folder_follow_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as folder, \
                unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": folder}):
            self.assertEqual(hookset.settings_path("claude"), pathlib.Path(folder, "settings.json"))
            link = pathlib.Path(folder, "hooks", "merge-gate.py")
            link.parent.mkdir()
            link.symlink_to(KIT / "hooks" / "merge-gate.py")
            self.assertTrue(hookset._ours(str(link), MANIFEST, "~/kit"))

    def test_an_older_link_in_dot_claude_stays_ours_under_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as folder, \
                unittest.mock.patch.dict(os.environ, {"HOME": home, "CLAUDE_CONFIG_DIR": folder}):
            link = pathlib.Path(home, ".claude", "hooks", "merge-gate.py")
            link.parent.mkdir(parents=True)
            link.symlink_to(KIT / "hooks" / "merge-gate.py")
            self.assertTrue(hookset._ours("~/.claude/hooks/merge-gate.py", MANIFEST, "~/kit"))


if __name__ == "__main__":
    unittest.main()

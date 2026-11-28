import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest, unittest.mock

import hook_parity, render_hooks

HOOKS = pathlib.Path(__file__).resolve().parent
MANIFEST = json.loads((HOOKS / "manifest.json").read_text())
DARWIN_ONLY = {e["command"] for entries in MANIFEST.values() for e in entries if e.get("hosts") == ["darwin"]}
sys.path.append(str(HOOKS.parent / "lib"))
import config  # noqa: E402
import hookset  # noqa: E402


def setUpModule():
    """A built resolved.json that selects every hook, for this checkout as the kit, which
    the wrappers read in this process and in the CLIs the tests run."""
    state = pathlib.Path(tempfile.mkdtemp())
    unittest.addModuleCleanup(shutil.rmtree, state)
    user = state / "addystack.jsonc"
    # Each reply hook needs its preference on, so this names reply-shape and a rules file.
    # A trial hook, which no preset includes, is selected by its id.
    every = sorted({entry["id"] for entries in MANIFEST.values() for entry in entries})
    user.write_text(json.dumps({"hooks": {"preset": "all", "enable": every}, "replies": {
        "style": "reply-shape", "rules": str(HOOKS / "README.md"), "turnBlock": True}}))
    (state / "resolved.json").write_text(json.dumps(config.resolve(user)))
    for patch in (unittest.mock.patch.dict(os.environ, {"ADDYSTACK_STATE": str(state)}),
                  unittest.mock.patch.object(hook_parity.resolved, "STATE", state / "resolved.json")):
        patch.start()
        unittest.addModuleCleanup(patch.stop)


def filled(command):
    """A manifest command with `{{kit}}` as the wrappers fill it for the current $HOME."""
    return command.replace("{{kit}}", hookset._kit({"kit": str(HOOKS.parent)}))


def commands(hooks):
    return [hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]]


class RenderedHome:
    """A fake home whose settings.json and hooks.json hold render(runtime, profile). The
    commands run this checkout's scripts, by absolute path, since it isn't under the home."""

    def __init__(self, test, profile):
        self.home = pathlib.Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.home)
        patch = unittest.mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                      "CLAUDE_CONFIG_DIR": str(self.home / ".claude")})
        patch.start()
        test.addCleanup(patch.stop)
        for runtime in hook_parity.RUNTIMES:
            self.write(runtime, render_hooks.render(runtime, profile))

    def path(self, runtime):
        return self.home / {"claude": ".claude/settings.json", "codex": ".codex/hooks.json"}[runtime]

    def write(self, runtime, hooks):
        self.path(runtime).parent.mkdir(parents=True, exist_ok=True)
        self.path(runtime).write_text(render_hooks.dumps({"hooks": hooks}))


class Render(unittest.TestCase):
    def test_every_hosts_value_is_a_profile(self):
        for runtime, entries in MANIFEST.items():
            for entry in entries:
                with self.subTest(command=entry["command"]):
                    self.assertLessEqual(set(entry.get("hosts", [])), set(hook_parity.PROFILES))

    def test_rendered_output_has_no_drift_on_its_own_profile(self):
        for profile in hook_parity.PROFILES:
            with self.subTest(profile=profile):
                RenderedHome(self, profile)
                self.assertEqual(hook_parity.drift("claude", profile=profile) +
                                 hook_parity.drift("codex", profile=profile), [])

    def test_darwin_only_hooks_render_only_on_darwin(self):
        self.assertTrue(DARWIN_ONLY)
        darwin_only = set(map(filled, DARWIN_ONLY))
        self.assertLessEqual(darwin_only, set(commands(render_hooks.render("claude", "darwin"))))
        for profile in ("linux", "sandbox"):
            self.assertFalse(darwin_only & set(commands(render_hooks.render("claude", profile))))

    def test_groups_hooks_by_event_and_matcher_in_manifest_order(self):
        hooks = render_hooks.render("claude", "darwin")
        events = list(dict.fromkeys(e["event"] for e in MANIFEST["claude"]))
        self.assertEqual(list(hooks), events)
        for event, groups in hooks.items():
            matchers = [group.get("matcher") for group in groups]
            self.assertEqual(len(matchers), len(set(matchers)), event)
        bash = next(g for g in hooks["PreToolUse"] if g.get("matcher") == "Bash")["hooks"]
        self.assertEqual([h["command"] for h in bash],
                         [filled(e["command"]) for e in MANIFEST["claude"] if e["event"] == "PreToolUse" and e["matcher"] == "Bash"])
        self.assertEqual(next(h for h in bash if h["command"].endswith("merge-gate.py")),
                         {"type": "command", "command": filled("{{kit}}/hooks/merge-gate.py"), "timeout": 60, "onFailure": "block"})
        self.assertNotIn("matcher", hooks["SessionStart"][0])

    def test_each_event_runs_in_manifest_order(self):
        for runtime in hook_parity.RUNTIMES:
            for profile in hook_parity.PROFILES:
                with self.subTest(runtime=runtime, profile=profile):
                    hooks = render_hooks.render(runtime, profile)
                    for event in hooks:
                        self.assertEqual(commands({event: hooks[event]}),
                                         [e["command"] for e in hook_parity.declared(runtime, profile) if e["event"] == event])

    def test_interleaved_matchers_keep_their_order(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = pathlib.Path(folder, "manifest.json")
            manifest.write_text(json.dumps({"codex": [
                {"id": name, "tags": ["safety"], "event": "PreToolUse", "matcher": matcher, "command": name, "timeout": 1}
                for name, matcher in (("a", "Bash"), ("b", "Write"), ("c", "Bash"))]}))
            with unittest.mock.patch.object(hook_parity, "MANIFEST", manifest):
                hooks = render_hooks.render("codex", "linux")
        self.assertEqual(commands(hooks), ["a", "b", "c"])
        self.assertEqual([g["matcher"] for g in hooks["PreToolUse"]], ["Bash", "Write", "Bash"])

    def test_codex_hooks_keep_their_trusted_order(self):
        """Codex trusts a hook by its position, so moving one untrusts it on every machine."""
        hooks = render_hooks.render("codex", "darwin")
        names = {event: [pathlib.PurePath(c.split()[0]).name for c in commands({event: groups})]
                 for event, groups in hooks.items()}
        # A new hook goes after the trusted ones, so their positions hold.
        self.assertEqual(names["PreToolUse"], ["merge-gate.py", "ready-gate.py", "push-gate.py",
                                               "agent-memory-guard-notice.py", "stack-gate.py"])
        self.assertEqual([len(groups) for groups in hooks.values()], [1, 1, 1])

    def cli(self, *args):
        return subprocess.run([sys.executable, str(HOOKS / "render_hooks.py"), *args],
                              capture_output=True, text=True, check=True).stdout

    def test_into_replaces_only_the_hooks_key_and_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = pathlib.Path(folder, "settings.json")
            settings.write_text(json.dumps({"env": {"A": "1"}, "hooks": {"Stop": []}, "model": "opus", "tui": "é"}))
            first = self.cli("--runtime", "claude", "--profile", "darwin", "--into", str(settings))
            self.assertEqual(list(json.loads(first)), ["env", "hooks", "model", "tui"])
            self.assertEqual(json.loads(first)["hooks"], render_hooks.render("claude", "darwin"))
            self.assertIn('"tui": "é"\n}\n', first)
            settings.write_text(first)
            out = pathlib.Path(folder, "out.json")
            self.cli("--runtime", "claude", "--profile", "darwin", "--into", str(settings), "--out", str(out))
            self.assertEqual(out.read_text(), first)

    def test_into_keeps_a_users_own_hooks_and_replaces_the_kits(self):
        # A hook an install recorded in its ledger is the kit's, though the manifest dropped
        # it; a user's own hook on a script in the kit's folder stays.
        ledger = pathlib.Path(os.environ["ADDYSTACK_STATE"], "installed.json")
        stale_command = f"{HOOKS}/no-longer-in-the-manifest.py"
        ledger.write_text(json.dumps({"version": 1, "hooks": {"claude": [["SessionStart", stale_command]]}}))
        self.addCleanup(ledger.unlink)
        with tempfile.TemporaryDirectory() as folder:
            settings = pathlib.Path(folder, "settings.json")
            mine = {"hooks": [{"type": "command", "command": "~/bin/mine.sh"}]}
            mine_in_kit = {"hooks": [{"type": "command", "command": f"{HOOKS}/my-personal-hook.sh"}]}
            stale = {"hooks": [{"type": "command", "command": stale_command}]}
            settings.write_text(json.dumps({"hooks": {"SessionStart": [mine, stale, mine_in_kit], "Notification": [mine]}}))
            hooks = json.loads(self.cli("--runtime", "claude", "--profile", "darwin", "--into", str(settings)))["hooks"]
            self.assertEqual(hooks["Notification"], [mine])
            self.assertEqual(hooks["SessionStart"], [mine, *render_hooks.render("claude", "darwin")["SessionStart"], mine_in_kit])

    def test_without_into_prints_a_hooks_file(self):
        out = self.cli("--runtime", "codex", "--profile", "linux")
        self.assertEqual(out, render_hooks.dumps({"hooks": render_hooks.render("codex", "linux")}))


class ParityProfiles(unittest.TestCase):
    def test_a_darwin_only_hook_missing_on_linux_isnt_drift(self):
        home = RenderedHome(self, "linux")
        self.assertEqual(hook_parity.drift("claude", profile="linux"), [])
        self.assertEqual(sorted(line.split()[-1] for line in hook_parity.drift("claude", profile="darwin")),
                         sorted(filled(e["command"]) for e in MANIFEST["claude"] if e.get("hosts") == ["darwin"]))
        self.assertTrue(all(line.startswith("claude: missing ") for line in hook_parity.drift("claude", profile="darwin")))
        home.write("claude", render_hooks.render("claude", "darwin"))  # present on linux: not extra either
        self.assertEqual(hook_parity.drift("claude", profile="linux"), [])

    def test_a_hook_for_every_host_is_still_required_on_linux(self):
        home = RenderedHome(self, "linux")
        hooks = render_hooks.render("claude", "linux")
        for group in hooks["PreToolUse"]:
            group["hooks"] = [h for h in group["hooks"] if not h["command"].endswith("ready-gate.py")]
        home.write("claude", hooks)
        self.assertEqual(hook_parity.drift("claude", profile="sandbox"),
                         [f"claude: missing PreToolUse {filled('{{kit}}/hooks/ready-gate.py')}"])

    def test_a_reordered_hook_is_drift(self):
        home = RenderedHome(self, "darwin")
        hooks = render_hooks.render("codex", "darwin")
        start = hooks["SessionStart"][0]["hooks"]
        start[1], start[2] = start[2], start[1]
        home.write("codex", hooks)
        self.assertEqual(hook_parity.drift("codex", profile="darwin"), [
            "codex: SessionStart runs reply-shape-context.py, skills-checkout-check.py, reply-shape-context.py --rules; "
            "manifest order is reply-shape-context.py, reply-shape-context.py --rules, skills-checkout-check.py"])

    def test_regrouping_without_reordering_isnt_drift(self):
        home = RenderedHome(self, "darwin")
        hooks = render_hooks.render("codex", "darwin")
        hooks["SessionStart"] = [{"hooks": [hook]} for hook in hooks["SessionStart"][0]["hooks"]]
        home.write("codex", hooks)
        self.assertEqual(hook_parity.drift("codex", profile="darwin"), [])

    def test_auto_profile(self):
        with unittest.mock.patch.dict(os.environ, {"SBX_SANDBOX": "1"}):
            self.assertEqual(hook_parity.host_profile(), "sandbox")
        with unittest.mock.patch.dict(os.environ, {"SBX_SANDBOX": ""}):
            self.assertEqual(hook_parity.host_profile(), "darwin" if sys.platform == "darwin" else "linux")
        with self.assertRaises(ValueError):
            hook_parity.host_profile("windows")

    def test_cli_profile(self):
        home = RenderedHome(self, "linux")
        def cli(*args):
            result = subprocess.run([sys.executable, str(HOOKS / "hook_parity.py"), "--codex", str(home.path("codex")), *args],
                                    capture_output=True, text=True, env={**os.environ, "HOME": str(home.home)})
            return result.returncode, result.stdout
        self.assertEqual(cli("--profile", "linux"), (0, "hooks match manifest.json\n"))
        code, out = cli("--profile", "darwin")
        self.assertEqual(code, 1)
        self.assertIn(f"claude: missing PreToolUse {HOOKS}/keychain-home-guard.py", out)


if __name__ == "__main__":
    unittest.main()

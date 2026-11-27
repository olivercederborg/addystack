import copy, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, tomllib, unittest, unittest.mock

import env_fingerprint as fp
import kit_path  # env_fingerprint put maintainer/ on the path.

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "maintainer" / "env_fingerprint.py"
sys.path.insert(0, str(kit_path.tool() / "hooks"))
import hook_parity, render_hooks  # noqa: E402
sys.path.append(str(kit_path.tool() / "lib"))
import config  # noqa: E402

SECRET = "sk-test-NEVER-PRINT-ME"
VERSIONS = {"claude": "2.1.316 (Claude Code)", "codex": "codex-cli 0.166.0", "t3": "t3 v0.1.6-nightly.20261031.3977",
            "gh": "gh version 2.103.3 (2026-10-26)", "node": "v24.21.0"}


def git(*args, cwd=None):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def git_tree(folder):
    """git's own tree SHA for folder, through a throwaway repo and index."""
    with tempfile.TemporaryDirectory() as repo:
        git("init", "-q", repo)
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(repo, "index")}
        subprocess.run(["git", "--work-tree", str(folder), "add", "-A", "."], cwd=repo, env=env, check=True)
        return subprocess.run(["git", "write-tree"], cwd=repo, env=env, check=True, capture_output=True,
                              text=True).stdout.strip()


class FakeHome:
    """A home that passes every check on profile darwin: a clean kit, a clean yadm, the
    manifest's hooks rendered, one kit skill, one remote skill matching .skill-lock.json, a
    git identity, MCP servers whose config holds a secret, and stub CLIs."""

    def __init__(self, test):
        self.test = test
        self.home = pathlib.Path(tempfile.mkdtemp()).resolve()
        test.addCleanup(shutil.rmtree, self.home)
        self.bin = self.home / "bin"
        self.kit = self.home / "Developer/personal/skills"
        self.versions = dict(VERSIONS)
        self.stubs()
        self.build_kit()
        self.build_skills()
        self.build_config()
        self.build_yadm()

    def file(self, relative, text, mode=None):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if mode:
            path.chmod(mode)
        return path

    def stubs(self):
        for name, version in self.versions.items():
            self.file(f"bin/{name}", f"#!/bin/sh\necho '{version}'\n", 0o755)
        self.file("bin/gh", f"#!/bin/sh\nif [ \"$1\" = extension ]; then printf 'gh stack\\tgithub/gh-stack\\tv0.2.1\\n'; "
                            f"else echo '{self.versions['gh']}'; fi\n", 0o755)
        self.file("bin/yadm", '#!/bin/sh\nexec git --git-dir="$HOME/.yadm.git" --work-tree="$HOME" "$@"\n', 0o755)

    def build_kit(self):
        self.file("Developer/personal/skills/reply-shape/SKILL.md", "---\nname: reply-shape\n---\n")
        for entries in json.loads(hook_parity.MANIFEST.read_text()).values():
            for entry in entries:
                for word in entry["command"].split():
                    if word.startswith("{{kit}}/"):
                        self.file(f"Developer/personal/skills/{word.removeprefix('{{kit}}/')}", "")
        (self.home / ".claude/hooks").mkdir(parents=True, exist_ok=True)
        # A build that selects every hook, at the state path ~ gives, so the fingerprint's
        # wrappers read it.
        user = self.file(".config/addystack/addystack.jsonc",
                         '{ "hooks": { "preset": "all" }, "replies": { "turnBlock": true } }')
        self.file(".local/state/addystack/resolved.json",
                  json.dumps(config.merge(config.load_layers(user), self.kit)))
        git("init", "-q", "-b", "main", str(self.kit))
        git("add", "-A", cwd=self.kit)
        git("commit", "-qm", "kit", cwd=self.kit)
        git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.kit)

    def build_skills(self):
        agents = self.home / ".agents/skills"
        claude = self.home / ".claude/skills"
        agents.mkdir(parents=True)
        claude.mkdir(parents=True)
        (agents / "reply-shape").symlink_to("../../Developer/personal/skills/reply-shape")
        self.file(".agents/skills/animate/SKILL.md", "---\nname: animate\n---\n")
        self.file(".agents/skills/animate/scripts/run.sh", "#!/bin/sh\n", 0o755)
        for name in ("reply-shape", "animate"):
            (claude / name).symlink_to(f"../../.agents/skills/{name}")
        self.file(".agents/.skill-lock.json", json.dumps({"version": 3, "skills": {"animate": {
            "source": "emilkowalski/skills", "skillPath": "skills/animate/SKILL.md",
            "skillFolderHash": git_tree(agents / "animate")}}}))

    def build_config(self):
        for runtime, path in hook_parity.PATHS.items():
            document = {"model": "opus", "env": {"TOKEN": SECRET}} if runtime == "claude" else {}
            document["hooks"] = self.render(runtime, "darwin")
            self.file(path.removeprefix("~/"), render_hooks.dumps(document))
        self.file(".claude/CLAUDE.md", "# rules\n")
        self.file(".codex/AGENTS.md", "# rules\n")
        self.file(".claude.json", json.dumps({"mcpServers": {"executor": {"headers": {"Authorization": f"Bearer {SECRET}"}}}}))
        self.file(".codex/config.toml", f'[mcp_servers.executor]\nurl = "x"\n[mcp_servers.executor.http_headers]\n'
                                        f'Authorization = "{SECRET}"\n[mcp_servers."node repl"]\ncommand = "n"\n')
        self.file(".config/yadm/agent-skills.json", json.dumps({"version": 1, "cli": "skills@1.5.9"}))
        self.file(".gitconfig", "[user]\n\tname = Oliver Cederborg\n\temail = hey@olivercederborg.com\n")
        self.file(".gitignore", "/.agents/skills/*\n")  # as dotfiles ignores installed remote skills

    def build_yadm(self):
        git("init", "-q", "--bare", str(self.home / ".yadm.git"))
        yadm = ["--git-dir", str(self.home / ".yadm.git"), "--work-tree", str(self.home)]
        git(*yadm, "add", "-f", ".claude/settings.json", ".codex/hooks.json", ".config/yadm/agent-skills.json", ".gitconfig",
            ".agents/.skill-lock.json", ".codex/AGENTS.md", ".claude/CLAUDE.md", ".codex/config.toml")
        # tracked in dotfiles, so not untracked agent files
        git(*yadm, "commit", "-qm", "dotfiles")

    def render(self, runtime, profile):
        """render_hooks.render in this home, from its resolved.json."""
        state = self.home / ".local/state/addystack/resolved.json"
        with unittest.mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                unittest.mock.patch.object(hook_parity.resolved, "STATE", state):
            return render_hooks.render(runtime, profile)

    def env(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "SBX_", "ADDYSTACK_"))}
        # The kit stays the real checkout: its default sits under the real HOME.
        return {**env, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1", "PATH": f"{self.bin}:/usr/bin:/bin", "ADDYSTACK_KIT": str(kit_path.repo())}

    def run(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--profile", "darwin", *args],
                                capture_output=True, text=True, env=self.env())
        return result.returncode, result.stdout, result.stderr

    def json(self, *args):
        code, out, err = self.run("--json", *args)
        self.test.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def lock(self, change=None):
        """A lock written from this home's own fingerprint, after change(lock)."""
        _, report = self.json()
        lock = {"version": fp.LOCK_VERSION, "createdAt": "2026-11-01T10:00:00Z", **copy.deepcopy(report["pinned"])}
        for name, pin in lock["cli"].items():
            pin["match"] = "exact"
        lock["profiles"] = {"darwin": {"exclude": []}, "linux": {"exclude": []}, "sandbox": {"extends": "linux"}}
        if change:
            change(lock)
        locks = pathlib.Path(tempfile.mkdtemp())
        self.test.addCleanup(shutil.rmtree, locks)
        path = locks / "env.lock.json"
        path.write_text(json.dumps(lock))
        return str(path)

    def drift(self, report):
        return [line for section in report["sections"].values() for line in section["drift"]]


class TreeSha(unittest.TestCase):
    def test_matches_git_write_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder, "skill")
            (root / "a/b").mkdir(parents=True)
            (root / "a-b").write_text("dash sorts before slash")
            (root / "a/b/deep.md").write_text("deep\n")
            (root / "run.sh").write_text("#!/bin/sh\n")
            (root / "run.sh").chmod(0o755)
            (root / "link").symlink_to("run.sh")
            (root / "empty").mkdir()
            self.assertEqual(fp.tree_sha(root), git_tree(root))
            (root / "__pycache__").mkdir()
            (root / "__pycache__/x.cpython-315.pyc").write_bytes(b"\0")
            (root / "y.pyc").write_bytes(b"\0")
            (root / ".DS_Store").write_bytes(b"\0")
            self.assertEqual(fp.tree_sha(root), git_tree_without(root, ("__pycache__", "*.pyc", ".DS_Store")))


def git_tree_without(root, names):
    with tempfile.TemporaryDirectory() as copy_root:
        target = pathlib.Path(copy_root, "c")
        shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(*names))
        return git_tree(target)


class FindKit(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home)
        (self.home / ".claude/skills").mkdir(parents=True)
        patcher = unittest.mock.patch.object(fp, "home", lambda: self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def link(self, target):
        (self.home / target).mkdir(parents=True)
        (self.home / ".claude/skills/reply-shape").symlink_to(self.home / target)

    def test_a_checkout_with_skill_layers_is_its_root(self):
        self.link("kit/skills/optional/reply-shape")
        self.assertEqual(fp.find_kit(), self.home / "kit")

    def test_a_flat_kit_is_the_skills_parent(self):
        self.link("kit/reply-shape")
        self.assertEqual(fp.find_kit(), self.home / "kit")

    def test_without_a_reply_shape_link_it_is_the_addystack_kit_checkout(self):
        self.assertEqual(fp.find_kit(), kit_path.repo())


class Versions(unittest.TestCase):
    def test_match_rules(self):
        self.assertTrue(fp.version_ok("0.166.0", {"version": "0.166.0", "match": "exact"}))
        self.assertFalse(fp.version_ok("0.162.1", {"version": "0.166.0", "match": "exact"}))
        self.assertTrue(fp.version_ok("2.103.3", {"version": "2.102.0", "match": "floor"}))
        self.assertFalse(fp.version_ok("2.101.9", {"version": "2.102.0", "match": "floor"}))
        self.assertTrue(fp.version_ok("24.21.0", {"version": "24", "match": "major"}))
        self.assertFalse(fp.version_ok("22.1.0", {"version": "24", "match": "major"}))
        self.assertTrue(fp.version_ok("0.2.1", {"version": "v0.2.1", "match": "exact"}))
        self.assertFalse(fp.version_ok(None, {"version": "1", "match": "floor"}))
        self.assertEqual(fp._version("t3 v0.1.6-nightly.20261031.3977"), "0.1.6-nightly.20261031.3977")
        self.assertEqual(fp._version("gh version 2.103.3 (2026-10-26)"), "2.103.3")


class Fingerprint(unittest.TestCase):
    def setUp(self):
        self.home = FakeHome(self)

    def test_a_clean_home_passes_without_a_lock(self):
        code, report = self.home.json()
        self.assertEqual(self.home.drift(report), [])
        self.assertEqual(code, 0)
        self.assertEqual(report["profile"], "darwin")
        self.assertEqual(list(report["sections"]), [s for s in fp.SECTIONS if s != "codex-trust"])
        pinned = report["pinned"]
        self.assertEqual(pinned["cli"]["codex"], {"version": "0.166.0"})
        self.assertEqual(pinned["cli"]["gh-stack"], {"version": "0.2.1"})
        self.assertEqual(pinned["cli"]["skills"], {"version": "1.5.9"})
        self.assertEqual(pinned["skills"]["agents"], ["animate", "reply-shape"])
        self.assertEqual(sorted(pinned["skills"]["claude"]), ["animate", "reply-shape"])
        self.assertEqual(pinned["remoteSkills"]["animate"]["skillPath"], "skills/animate")
        self.assertEqual(pinned["mcp"], {"darwin": {"claude": ["executor"], "codex": ["executor", "node repl"]}})
        self.assertEqual(pinned["git"], {"user.name": "Oliver Cederborg", "user.email": "hey@olivercederborg.com"})

    def test_text_output(self):
        code, out, _ = self.home.run()
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("env fingerprint · profile darwin · no lock\nkit        ok    "))
        self.assertRegex(out, r"\nfingerprint [0-9a-f]{12}\n$")

    def test_never_prints_a_secret(self):
        for args in ((), ("--json",)):
            _, out, err = self.home.run(*args)
            self.assertNotIn(SECRET, out + err)

    def test_reads_only(self):
        def snapshot():
            return {str(p): (p.lstat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "")
                    for p in self.home.home.rglob("*")}
        before = snapshot()
        self.home.run("--json")
        self.home.run("--lock", self.home.lock())
        self.assertEqual(snapshot(), before)

    def test_its_own_lock_passes(self):
        code, report = self.home.json("--lock", self.home.lock())
        self.assertEqual((code, self.home.drift(report)), (0, []))
        self.assertRegex(report["lockSha256"], "^[0-9a-f]{64}$")

    def test_lock_drift_names_each_mismatch(self):
        def change(lock):
            lock["cli"]["codex"]["version"] = "0.162.1"
            lock["git"]["user.email"] = "other@example.com"
            lock["remoteSkills"]["animate"]["tree"] = "0" * 40
            lock["skills"]["agents"].append("sharpen")
            lock["mcp"]["darwin"]["claude"].append("xcode")
            lock["kit"]["sha"] = "1" * 40
        code, report = self.home.json("--lock", self.home.lock(change))
        self.assertEqual(code, 1)
        drift = self.home.drift(report)
        self.assertIn("cli: codex 0.166.0 ≠ lock 0.162.1 (exact)", drift)
        self.assertIn("git: user.email hey@olivercederborg.com ≠ lock other@example.com", drift)
        self.assertIn("skills: missing ~/.agents/skills/sharpen", drift)
        self.assertTrue(any(line.startswith("skills: animate tree ") and line.endswith("≠ lock 0000000") for line in drift))
        self.assertIn("mcp: claude missing xcode", drift)
        self.assertTrue(any(line.startswith("kit: HEAD ") and line.endswith("≠ lock 1111111") for line in drift))
        self.assertFalse(report["sections"]["hooks"]["drift"])

    def test_profile_exclusions_and_extends(self):
        def change(lock):
            lock["skills"]["agents"].append("using-executor")
            lock["mcp"]["sandbox"] = {"claude": ["executor"], "codex": ["executor", "node repl"]}
            lock["hooks"]["renderedSha256"]["claude:sandbox"] = lock["hooks"]["renderedSha256"]["claude:darwin"]
            lock["hooks"]["renderedSha256"]["codex:sandbox"] = lock["hooks"]["renderedSha256"]["codex:darwin"]
            lock["profiles"]["linux"]["exclude"] = ["skill:using-executor"]
        lock = self.home.lock(change)
        _, report = self.home.json("--lock", lock)
        self.assertIn("skills: missing ~/.agents/skills/using-executor", self.home.drift(report))
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", "sandbox", "--lock", lock],
                                capture_output=True, text=True, env=self.home.env())
        self.assertEqual(json.loads(result.stdout)["sections"]["skills"]["drift"], [])

    def test_lock_free_drift(self):
        home = self.home
        (home.home / ".agents/skills/sharpen").symlink_to("../../Developer/personal/skills/sharpen")
        (home.home / ".agents/skills/animate/SKILL.md").write_text("edited\n")
        (home.home / ".gitconfig").write_text("")
        (home.bin / "t3").unlink()
        (home.kit / "reply-shape/SKILL.md").write_text("edited\n")
        settings = json.loads((home.home / ".claude/settings.json").read_text())
        settings["hooks"]["PreToolUse"][0]["hooks"].pop()
        (home.home / ".claude/settings.json").write_text(render_hooks.dumps(settings))
        code, report = home.json()
        drift = home.drift(report)
        self.assertEqual(code, 1)
        self.assertIn("skills: dangling link ~/.agents/skills/sharpen → ../../Developer/personal/skills/sharpen", drift)
        self.assertTrue(any(line.startswith("skills: animate tree ") and ".skill-lock.json" in line for line in drift))
        self.assertIn("git: user.name unset", drift)
        self.assertIn("cli: t3 not found", drift)
        self.assertIn("kit: M reply-shape/SKILL.md", drift)
        self.assertIn("yadm: M .claude/settings.json", drift)
        self.assertTrue(any(line.startswith("claude: missing PreToolUse ") for line in drift))

    def test_installed_hooks_must_equal_the_locked_render(self):
        lock = self.home.lock()
        settings = self.home.home / ".claude/settings.json"
        document = json.loads(settings.read_text())
        document["hooks"] = self.home.render("claude", "linux")  # darwin-only hooks gone
        settings.write_text(render_hooks.dumps(document))
        _, report = self.home.json("--lock", lock)
        self.assertEqual([line.split(" installed")[0] for line in report["sections"]["hooks"]["drift"]
                          if "installed" in line], ["hooks: claude"])
        self.assertTrue(any(line.startswith("claude: missing PreToolUse ") for line in report["sections"]["hooks"]["drift"]))

    def test_codex_trust_runs_hook_paritys_check(self):
        code, report = self.home.json("--codex-trust")  # the stub codex answers no JSON-RPC
        self.assertEqual(code, 1)
        [line] = report["sections"]["codex-trust"]["drift"]
        self.assertTrue(line.startswith("codex trust: not checked, codex app-server didn't answer: "), line)

    def test_a_reordered_or_regrouped_hook_mismatches_the_lock(self):
        lock = self.home.lock()
        path = self.home.home / ".codex/hooks.json"
        hooks = self.home.render("codex", "darwin")
        # Same order, new groups: one group per PreToolUse hook, each keeping its matcher.
        hooks["PreToolUse"] = [{**group, "hooks": [hook]} for group in hooks["PreToolUse"] for hook in group["hooks"]]
        path.write_text(render_hooks.dumps({"hooks": hooks}))
        _, report = self.home.json("--lock", lock)
        self.assertEqual([line.split(" ≠ ")[0] for line in report["sections"]["hooks"]["drift"]],
                         ["hooks: codex installed " + report["sections"]["hooks"]["observed"]["installedSha256"]["codex"][:7]])
        # Rendered groups, two hooks swapped: the order alone changes.
        hooks = self.home.render("codex", "darwin")
        first = hooks["PreToolUse"][0]["hooks"]
        first[0], first[1] = first[1], first[0]
        path.write_text(render_hooks.dumps({"hooks": hooks}))
        _, report = self.home.json("--lock", lock)
        drift = report["sections"]["hooks"]["drift"]
        self.assertTrue(any(line.startswith("hooks: codex installed ") for line in drift), drift)
        # The kit's test_render_hooks checks what the order line says.
        self.assertTrue(any(line.startswith("codex: PreToolUse runs ") for line in drift), drift)

    def test_invalid_lock_exits_2(self):
        for change in (lambda lock: lock.update(version=99), lambda lock: lock["cli"]["codex"].update(match="any"),
                       lambda lock: lock.pop("settingsSha256"), lambda lock: lock["profiles"].update(windows={})):
            with self.subTest():
                code, out, err = self.home.run("--lock", self.home.lock(change))
                self.assertEqual((code, out), (2, ""))
                self.assertIn("invalid lock", err)


class StatusFailures(unittest.TestCase):
    """A git status that fails or times out must not read as clean."""

    def setUp(self):
        self.home = FakeHome(self)

    def test_a_failed_kit_status_is_drift(self):
        (self.home.kit / ".git/index").write_bytes(b"not an index")  # status fails; rev-parse HEAD still works
        code, report = self.home.json()
        self.assertEqual(code, 1)
        self.assertIn("kit: git status failed or timed out, so its cleanliness is unknown", report["sections"]["kit"]["drift"])
        self.assertIs(report["sections"]["kit"]["observed"]["statusOk"], False)

    def test_a_failed_yadm_status_is_drift(self):
        self.home.file("bin/yadm", '#!/bin/sh\n[ "$1" = status ] && exit 128\n'
                                   'exec git --git-dir="$HOME/.yadm.git" --work-tree="$HOME" "$@"\n', 0o755)
        code, report = self.home.json()
        self.assertEqual(code, 1)
        self.assertEqual(report["sections"]["yadm"]["drift"],
                         ["yadm: yadm status failed or timed out, so its cleanliness is unknown"])
        self.assertIs(report["sections"]["yadm"]["observed"]["statusOk"], False)

    def test_compare_flags_a_failed_status_once(self):
        lock = self.home.lock()
        (self.home.kit / ".git/index").write_bytes(b"not an index")
        _, report = self.home.json("--lock", lock)
        self.assertEqual(report["sections"]["kit"]["drift"],
                         ["kit: git status failed or timed out, so its cleanliness is unknown"])
        observed = {name: section["observed"] for name, section in report["sections"].items()}
        for name in ("kit", "yadm"):
            with self.subTest(name=name):
                broken = {**observed, name: {k: v for k, v in observed[name].items() if k != "statusOk"}}
                self.assertIn(f"{name}: {'git' if name == 'kit' else 'yadm'} status failed or timed out, so its "
                              "cleanliness is unknown", fp.compare(broken, json.loads(pathlib.Path(lock).read_text()),
                                                                  "darwin")[name])


class ClaudeSkills(unittest.TestCase):
    """Each ~/.claude/skills entry is a link or a folder with a content tree, and a folder
    yadm doesn't track is drift, since no other host can get it."""

    def setUp(self):
        self.home = FakeHome(self)
        self.claude = self.home.home / ".claude/skills"
        self.agents = self.home.home / ".agents/skills"

    def test_records_each_entry_kind_link_and_tree(self):
        _, report = self.home.json()
        self.assertEqual(report["pinned"]["skills"]["claude"], {
            "animate": {"kind": "link", "link": "../../.agents/skills/animate", "tree": git_tree(self.agents / "animate")},
            "reply-shape": {"kind": "link", "link": "../../.agents/skills/reply-shape",
                            "tree": git_tree(self.home.kit / "reply-shape")},
        })

    def test_an_untracked_folder_is_yadm_drift_and_links_and_caches_are_not(self):
        self.home.file(".claude/skills/use-railway/SKILL.md", "---\nname: use-railway\n---\n")
        self.home.file(".claude/skills/use-railway/references/a.md", "a\n")
        (self.claude / "animate-too").symlink_to("../../.agents/skills/animate")  # bootstrap-style link
        self.home.file(".claude/skills/synced/org_account/morning/SKILL.md", "x")  # Claude Code's claude.ai sync
        self.home.file(".config/yadm/bin/__pycache__/tool.cpython-315.pyc", "x")
        self.home.file(".claude/projects/session.jsonl", "x")  # runtime state outside the config folders
        code, report = self.home.json()
        self.assertEqual(code, 1)
        self.assertEqual(report["sections"]["yadm"]["drift"], ["yadm: ?? .claude/skills/use-railway/ (untracked, 2 files)"])
        claude = report["pinned"]["skills"]["claude"]
        self.assertEqual(claude["use-railway"]["kind"], "folder")
        self.assertEqual(claude["use-railway"]["tree"], git_tree(self.claude / "use-railway"))
        self.assertNotIn("synced", claude)

    def test_the_lock_compares_each_entry_kind_link_and_tree(self):
        lock = self.home.lock()
        (self.claude / "animate").unlink()
        shutil.copytree(self.agents / "animate", self.claude / "animate")  # same content, now a folder
        _, report = self.home.json("--lock", lock)
        self.assertIn("skills: ~/.claude/skills/animate is a folder; lock has a link to ../../.agents/skills/animate",
                      report["sections"]["skills"]["drift"])
        shutil.rmtree(self.claude / "animate")
        (self.claude / "animate").symlink_to(self.agents / "animate")  # same content, another target
        _, report = self.home.json("--lock", lock)
        self.assertIn(f"skills: ~/.claude/skills/animate is a link to {self.agents / 'animate'}; "
                      "lock has a link to ../../.agents/skills/animate", report["sections"]["skills"]["drift"])
        (self.claude / "animate").unlink()
        (self.claude / "animate").symlink_to("../../.agents/skills/animate")
        (self.agents / "animate/SKILL.md").write_text("edited\n")
        _, report = self.home.json("--lock", lock)
        self.assertTrue(any(line.startswith("skills: ~/.claude/skills/animate tree ") for line in
                            report["sections"]["skills"]["drift"]), report["sections"]["skills"]["drift"])

    def test_a_version_1_lock_is_refused_with_how_to_fix_it(self):
        code, out, err = self.home.run("--lock", self.home.lock(lambda lock: lock.update(version=1)))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("a version 1 lock records ~/.claude/skills by name only; rewrite it with sbx lock", err)

    def test_a_claude_row_without_a_kind_or_tree_is_invalid(self):
        for change in (lambda lock: lock["skills"]["claude"]["animate"].update(kind="file"),
                       lambda lock: lock["skills"]["claude"]["animate"].update(kind="folder"),  # a folder with a link
                       lambda lock: lock["skills"]["claude"]["animate"].update(tree=None),
                       lambda lock: lock["skills"]["claude"]["animate"].pop("link"),
                       lambda lock: lock["skills"].update(claude=["animate"])):
            with self.subTest():
                code, _, err = self.home.run("--lock", self.home.lock(change))
                self.assertEqual(code, 2, err)
                self.assertIn("skills.claude", err)

    def test_a_failed_untracked_status_is_drift(self):
        self.home.file("bin/yadm", '#!/bin/sh\ncase "$*" in *--untracked-files=all*) exit 128;; esac\n'
                                   'exec git --git-dir="$HOME/.yadm.git" --work-tree="$HOME" "$@"\n', 0o755)
        _, report = self.home.json()
        self.assertEqual(report["sections"]["yadm"]["drift"],
                         ["yadm: yadm status failed or timed out, so its cleanliness is unknown"])


class NestedLinks(unittest.TestCase):
    """A skill tree outside the kit can't hold a symlink, as restore-agent-skills refuses one."""

    def setUp(self):
        self.home = FakeHome(self)

    def test_a_link_inside_a_skill_folder_is_drift_on_every_profile(self):
        (self.home.home / ".agents/skills/animate/hosts").symlink_to("/etc/hosts")
        for profile in ("darwin", "linux"):
            with self.subTest(profile=profile):
                result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", profile],
                                        capture_output=True, text=True, env=self.home.env())
                self.assertIn("skills: ~/.agents/skills/animate holds a symlink (hosts), which a skill tree can't have",
                              self.home.drift(json.loads(result.stdout)))

    def test_links_inside_a_kit_skill_are_pinned_by_the_kit(self):
        (self.home.kit / "reply-shape/shared.md").symlink_to("SKILL.md")
        git("add", "-A", cwd=self.home.kit)
        git("commit", "-qm", "link", cwd=self.home.kit)
        git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.home.kit)
        code, report = self.home.json()
        self.assertEqual((code, self.home.drift(report)), (0, []))


class StrictSandbox(unittest.TestCase):
    """A sandbox is trusted because it's built from the lock and nothing else, so under
    --profile sandbox anything under the agent paths that yadm doesn't track and the lock
    doesn't pin is drift. darwin and linux stay lenient."""

    def setUp(self):
        self.home = FakeHome(self)
        self.lock = self.home.lock(self.sandbox_ready)
        self.outside = self.home.home / "elsewhere"
        self.outside.mkdir()

    @staticmethod
    def sandbox_ready(lock):
        """The fake home renders darwin hooks; a sandbox lock pins what it has."""
        rendered = lock["hooks"]["renderedSha256"]
        rendered["claude:sandbox"], rendered["codex:sandbox"] = rendered["claude:darwin"], rendered["codex:darwin"]
        lock["mcp"]["sandbox"] = lock["mcp"]["darwin"]

    def strict(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", "sandbox", "--lock", self.lock],
                                capture_output=True, text=True, env=self.home.env())
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode, self.home.drift(json.loads(result.stdout))

    def lenient(self):
        code, report = self.home.json()
        return code, self.home.drift(report)

    def test_a_home_built_from_the_lock_passes(self):
        self.assertEqual(self.strict(), (0, []))

    def test_each_entry_neither_yadm_nor_the_lock_accounts_for_is_drift(self):
        home, outside = self.home, self.outside
        (outside / "hook.py").write_text("")
        (outside / "helper.md").write_text("")

        def ignored_codex_rule():
            home.file(".gitignore", "/.agents/skills/*\n/.codex/rules/local.rules\n")
            home.file(".codex/rules/local.rules", "allow()\n")

        def ignored_agents_folder():
            home.file(".agents/skills/stray/SKILL.md", "---\nname: stray\n---\n")

        def untracked_hook_link():
            (home.home / ".claude/hooks/extra.py").symlink_to(outside / "hook.py")

        def linked_claude_agent():
            (home.home / ".claude/agents").mkdir(parents=True, exist_ok=True)
            (home.home / ".claude/agents/helper.md").symlink_to(outside / "helper.md")

        def claude_command():
            home.file(".claude/commands/ship.md", "ship it\n")

        def synced_skill():
            home.file(".claude/skills/synced/org_account/morning/SKILL.md", "x")

        cases = {
            ignored_codex_rule: "yadm: !! .codex/rules/local.rules isn't tracked by yadm or pinned by the lock",
            ignored_agents_folder: "yadm: !! .agents/skills/stray/ isn't tracked by yadm or pinned by the lock",
            untracked_hook_link: "yadm: ?? .claude/hooks/extra.py isn't tracked by yadm or pinned by the lock",
            linked_claude_agent: "yadm: ?? .claude/agents/helper.md isn't tracked by yadm or pinned by the lock",
            claude_command: "yadm: ?? .claude/commands/ship.md isn't tracked by yadm or pinned by the lock",
            synced_skill: "yadm: ~/.claude/skills/synced holds claude.ai skills, which a sandbox can't have",
        }
        for make, line in cases.items():
            with self.subTest(case=make.__name__):
                make()
                code, drift = self.strict()
                self.assertEqual(code, 1)
                self.assertIn(line, drift)
                self.assertEqual(self.lenient(), (0, []))  # the Mac and devbox stay lenient

    def test_links_into_the_locked_kit_are_pinned_by_its_sha(self):
        target = self.home.file("Developer/personal/skills/agents/work-verifier.md", "")
        git("add", "-A", cwd=self.home.kit)
        git("commit", "-qm", "agent", cwd=self.home.kit)
        git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.home.kit)
        self.lock = self.home.lock(self.sandbox_ready)
        (self.home.home / ".claude/agents").mkdir(parents=True, exist_ok=True)
        (self.home.home / ".claude/agents/work-verifier.md").symlink_to(target)
        self.assertEqual(self.strict(), (0, []))

    def test_a_kit_given_through_a_symlink_still_pins_its_links(self):
        """sbx lock passes --kit as given; a link to the kit is the same kit."""
        alias = self.home.home / "kit-alias"
        alias.symlink_to(self.home.kit)
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", "sandbox", "--lock", self.lock,
                                 "--kit", str(alias)], capture_output=True, text=True, env=self.home.env())
        self.assertEqual((result.returncode, self.home.drift(json.loads(result.stdout))), (0, []))

    def test_the_sandbox_profile_needs_a_lock(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", "sandbox"],
                                capture_output=True, text=True, env=self.home.env())
        self.assertIn("yadm: the sandbox profile checks against a lock; pass --lock",
                      self.home.drift(json.loads(result.stdout)))

    def test_bytecode_under_a_skill_is_drift_only_in_a_sandbox(self):
        self.home.file(".agents/skills/animate/scripts/__pycache__/run.cpython-315.pyc", "x")
        code, drift = self.strict()
        self.assertIn("skills: ~/.agents/skills/animate holds bytecode (scripts/__pycache__/run.cpython-315.pyc), "
                      "which a sandbox can't have", drift)
        self.assertEqual(self.lenient(), (0, []))

    def test_many_entries_in_one_folder_are_one_line(self):
        for name in ("a", "b", "c"):
            self.home.file(f".claude/commands/{name}.md", "x")
        code, drift = self.strict()
        self.assertEqual(drift, ["yadm: ?? .claude/commands/ (3 entries) isn't tracked by yadm or pinned by the lock"])

    def test_claude_codes_plugin_catalog_is_runtime_state_and_synced_plugins_are_not(self):
        self.home.file(".claude/plugins/marketplaces/claude-plugins-official/.gcs-sha", "x")
        self.home.file(".claude/plugins/marketplaces/claude-plugins-official/plugins/a/plugin.json", "{}")
        self.home.file(".claude/plugins/known_marketplaces.json", "{}")
        self.home.file(".claude/plugins/plugin-directory-cache-v2.json", "{}")
        self.home.file(".claude/plugins/.last_inuse_sweep", "x")
        self.assertEqual(self.strict(), (0, []))
        self.home.file(".claude/plugins/synced/org/p/plugin.json", "{}")
        self.assertEqual(self.strict()[1],
                         ["yadm: ?? .claude/plugins/synced/org/p/plugin.json isn't tracked by yadm or pinned by the lock"])

    def test_a_remote_skill_must_be_a_real_folder_and_a_sibling_link_isnt_an_alternate(self):
        """The lock pins a remote skill by its tree in ~/.agents/skills, not wherever a link
        points; only yadm's `name##…` link counts as an alternate."""
        agents = self.home.home / ".agents/skills"
        shutil.copytree(agents / "animate", self.outside / "animate")
        shutil.rmtree(agents / "animate")
        (agents / "animate").symlink_to(self.outside / "animate")
        (self.home.home / ".claude/notes.json").symlink_to("settings.json")  # tracked sibling, not name##…
        self.assertEqual(self.strict()[1], [
            "yadm: !! .agents/skills/animate isn't tracked by yadm or pinned by the lock",
            "yadm: ?? .claude/notes.json isn't tracked by yadm or pinned by the lock"])

    def test_a_yadm_alternate_link_is_tracked_through_its_target(self):
        """On Linux, ~/.claude/settings.json is an ignored link to the tracked settings.json##os.Linux."""
        settings = self.home.home / ".claude/settings.json"
        alternate = settings.with_name("settings.json##os.Linux")
        settings.rename(alternate)
        settings.symlink_to(alternate.name)
        yadm = ["--git-dir", str(self.home.home / ".yadm.git"), "--work-tree", str(self.home.home)]
        git(*yadm, "rm", "-q", "--cached", ".claude/settings.json")
        git(*yadm, "add", ".claude/settings.json##os.Linux")
        git(*yadm, "commit", "-qm", "alternate")
        self.home.file(".gitignore", "/.agents/skills/*\n/.claude/settings.json\n")
        self.lock = self.home.lock(self.sandbox_ready)
        self.assertEqual(self.strict(), (0, []))

    def test_a_runtime_pattern_matches_only_in_its_own_folder(self):
        """`.codex/*.sqlite` is Codex's state; the same name a folder down is not."""
        self.home.file(".codex/state.sqlite", "x")
        self.assertEqual(self.strict(), (0, []))
        self.home.file(".codex/rules/state.sqlite", "x")
        self.assertEqual(self.strict()[1],
                         ["yadm: ?? .codex/rules/state.sqlite isn't tracked by yadm or pinned by the lock"])

    def test_an_alternate_link_to_an_untracked_target_is_drift(self):
        claude = self.home.home / ".claude"
        (claude / "notes.json##os.Linux").write_text("{}")
        (claude / "notes.json").symlink_to("notes.json##os.Linux")
        self.assertEqual(self.strict()[1], [
            "yadm: ?? .claude/notes.json isn't tracked by yadm or pinned by the lock",
            "yadm: ?? .claude/notes.json##os.Linux isn't tracked by yadm or pinned by the lock"])

    def test_bytecode_in_a_kit_skill_is_drift_in_a_sandbox(self):
        """The kit ignores __pycache__/, so its SHA doesn't pin a kit skill's bytecode."""
        self.home.file("Developer/personal/skills/.gitignore", "__pycache__/\n")
        git("add", "-A", cwd=self.home.kit)
        git("commit", "-qm", "ignore bytecode", cwd=self.home.kit)
        git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.home.kit)
        self.lock = self.home.lock(self.sandbox_ready)
        self.home.file("Developer/personal/skills/reply-shape/__pycache__/x.cpython-315.pyc", "x")
        self.assertEqual(self.strict()[1], ["skills: ~/.agents/skills/reply-shape holds bytecode "
                                            "(__pycache__/x.cpython-315.pyc), which a sandbox can't have"])


class TrackedChanges(unittest.TestCase):
    """A tracked file under ~/.claude, ~/.agents or ~/.codex that differs from yadm HEAD is
    drift on every profile, .codex/config.toml included, except for the keys the Codex app
    rewrites on its own."""

    APP = "[mcp_servers.node_repl.env]\nBROWSER_USE_CODEX_APP_VERSION = \"{v}\"\nNODE_REPL_TRUSTED_SERVICES = " \
          "'{{\"browser\":\"/h/.codex/plugins/cache/openai-bundled/browser/{v}/scripts/browser-service.mjs\"}}'\n"
    VOLATILE = ('[hooks.state."/h/.codex/hooks.json:stop:0:2"]\ntrusted_hash = "sha256:ab"\n'
                '[projects."/tmp/x"]\ntrust_level = "trusted"\n')

    def setUp(self):
        self.home = FakeHome(self)
        self.config = self.home.home / ".codex/config.toml"
        self.config.write_text(self.config.read_text() + self.APP.format(v="26.930.21537"))
        self.yadm("commit", "-qam", "app")

    def yadm(self, *args):
        return git("--git-dir", str(self.home.home / ".yadm.git"), "--work-tree", str(self.home.home), *args)

    def drift(self, profile="darwin", *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", profile, *args],
                                capture_output=True, text=True, env=self.home.env())
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return self.home.drift(json.loads(result.stdout))

    def test_a_changed_tracked_codex_config_is_drift_on_every_profile(self):
        lock = self.home.lock(StrictSandbox.sandbox_ready)
        self.config.write_text(self.config.read_text().replace('url = "x"', 'url = "y"') + self.VOLATILE)
        for profile, args in (("darwin", []), ("linux", []), ("sandbox", ["--lock", lock])):
            with self.subTest(profile=profile):
                self.assertIn("yadm: M .codex/config.toml", self.drift(profile, *args))

    def test_the_keys_the_codex_app_rewrites_are_not_drift(self):
        lock = self.home.lock(StrictSandbox.sandbox_ready)
        self.config.write_text(self.config.read_text().replace("26.930.21537", "26.1007.71326") + self.VOLATILE)
        for profile, args in (("darwin", []), ("linux", []), ("sandbox", ["--lock", lock])):
            with self.subTest(profile=profile):
                self.assertNotIn("yadm: M .codex/config.toml", self.drift(profile, *args))

    def test_each_other_change_is_still_drift(self):
        changes = {
            "a top-level key": lambda text: 'model = "gpt-6"\n' + text,
            "an MCP server": lambda text: text + '[mcp_servers.new]\ncommand = "n"\n',
            "a secret": lambda text: text.replace(SECRET, SECRET + "2"),
            "a server's other env": lambda text: text + 'CODEX_HOME = "/elsewhere"\n',
            "a trusted service beyond the version": lambda text: text.replace("browser-service", "other-service"),
            "the version outside a path's folder": lambda text: text.replace(
                "browser-service", "browser-service-26.930.21537").replace("26.930.21537", "26.1007.71326"),
            "a hooks key beside state": lambda text: text + '[hooks.other]\nx = 1\n',
            "TOML that doesn't parse": lambda text: text + "[[",
            "a table that becomes a value": lambda text: 'mcp_servers = "off"\n',
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.yadm("checkout", "--", ".codex/config.toml")
                self.config.write_text(change(self.config.read_text()) + self.VOLATILE)
                self.assertIn("yadm: M .codex/config.toml", self.drift())

    def test_a_utf8_config_is_read_as_utf8_whatever_the_locale(self):
        self.config.write_text(self.config.read_text() + '[projects."/tmp/\u00e6"]\ntrust_level = "untrusted"\n',
                               encoding="utf-8")
        self.yadm("commit", "-qam", "project")
        self.config.write_text(self.config.read_text(encoding="utf-8").replace('"untrusted"', '"trusted"'),
                               encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--profile", "darwin"], capture_output=True,
                                text=True, encoding="utf-8", env={**self.home.env(), "LC_ALL": "C", "PYTHONUTF8": "0"})
        self.assertEqual(self.home.drift(json.loads(result.stdout)), [])

    def test_a_staged_volatile_change_is_not_drift(self):
        self.config.write_text(self.config.read_text() + self.VOLATILE)
        self.yadm("add", ".codex/config.toml")
        self.assertNotIn("yadm: M .codex/config.toml", self.drift())

    def test_shapes_and_types_the_codex_app_never_writes_are_drift(self):
        """Only the leaf keys the app writes drop out: a trust level, a hook's trusted hash,
        and the version, each a string. Anything else in those tables, or a value of another
        TOML type, is still compared. Each case is (edit to HEAD first, edit to the work tree)."""
        def without_services(text):
            return "".join(line for line in text.splitlines(True) if not line.startswith("NODE_REPL_TRUSTED_SERVICES"))
        cases = {
            "projects as a value": (None, lambda text: 'projects = "all"\n' + text),
            "hooks.state as a value": (None, lambda text: text + '[hooks]\nstate = "all"\n'),
            "another key in a project": (None, lambda text: text + '[projects."/tmp/x"]\nother = 1\n'),
            "another key in a hook's state": (None, lambda text: text + '[hooks.state."/h:stop:0:2"]\nother = 1\n'),
            "the version as a table": (without_services, lambda text: text.replace(
                '"26.930.21537"', "{ v = 1 }")),
            "true as 1": (lambda text: text.replace('command = "n"', 'command = "n"\nenabled = true'),
                          lambda text: text.replace("enabled = true", "enabled = 1")),
            "another env value holding the version": (lambda text: text + 'API_KEY = "k/26.930.21537/k"\n',
                                                      lambda text: text.replace("26.930.21537", "26.1007.71326")),
            "a path that spells the mask": (None, lambda text: text.replace("/browser/26.930.21537/", "/browser/<app version>/")),
            "nesting too deep to compare": (None, lambda text: text + "BAD = " + "[" * 1500 + "\n"),
            "trusted services as an array of the path's pieces": (None, lambda text: re.sub(
                r"^NODE_REPL_TRUSTED_SERVICES = .*$", lambda line: "NODE_REPL_TRUSTED_SERVICES = " + json.dumps(
                    tomllib.loads(text)["mcp_servers"]["node_repl"]["env"]["NODE_REPL_TRUSTED_SERVICES"].split(
                        "/26.930.21537/")), text, flags=re.M)),
            "a service name holding the version": (lambda text: text.replace('"browser":', '"browser/26.930.21537/x":'),
                                                   lambda text: text.replace("26.930.21537", "26.1007.71326")),
        }
        base = self.yadm("rev-parse", "HEAD")
        for name, (edit_head, edit_now) in cases.items():
            with self.subTest(name):
                self.yadm("reset", "-q", "--hard", base)
                if edit_head:
                    self.config.write_text(edit_head(self.config.read_text()))
                    self.yadm("commit", "-qam", name)
                self.config.write_text(edit_now(self.config.read_text()))
                self.assertIn("yadm: M .codex/config.toml", self.drift())

    def test_a_staged_change_under_a_restored_file_is_drift(self):
        text = self.config.read_text()
        self.config.write_text(text.replace('url = "x"', 'url = "y"'))
        self.yadm("add", ".codex/config.toml")
        self.config.write_text(text + self.VOLATILE)
        self.assertIn("yadm: MM .codex/config.toml", self.drift())

    def test_a_mode_change_is_drift(self):
        self.config.chmod(0o755)
        self.assertIn("yadm: M .codex/config.toml", self.drift())
        self.yadm("add", ".codex/config.toml")
        self.assertIn("yadm: M  .codex/config.toml", self.drift())

    def test_a_committed_config_that_isnt_utf8_is_drift(self):
        self.config.write_bytes(b"\xff")
        self.yadm("commit", "-qam", "bytes")
        self.assertIn("mcp: ~/.codex/config.toml isn't UTF-8, so its servers are unknown", self.drift())

    def test_a_config_that_isnt_utf8_is_drift_not_a_crash(self):
        text = self.config.read_text()
        for name, (head, now) in {"in the work tree": (None, b"\xff"), "in HEAD": (b"\xff", text.encode())}.items():  # HEAD's commit last
            with self.subTest(name):
                self.yadm("checkout", "--", ".codex/config.toml")
                if head is not None:
                    self.config.write_bytes(head)
                    self.yadm("commit", "-qam", "bytes")
                self.config.write_bytes(now)
                self.assertIn("yadm: M .codex/config.toml", self.drift())

    def test_a_deleted_codex_config_is_drift(self):
        self.config.unlink()
        self.assertIn("yadm: D .codex/config.toml", self.drift())


if __name__ == "__main__":
    unittest.main()

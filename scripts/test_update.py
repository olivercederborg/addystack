"""Tests for `addystack update` in a scratch HOME, run without a terminal as an agent runs
it. With an npx skills install it updates the skills, adds the core skills a release adds,
and removes the ones it dropped (plan check 10). With a maintainer's git checkout it moves
to the newest v* tag. Both then install. A stub skills CLI (ADDYSTACK_SKILLS_CLI) installs
from a local git "release" repo, so no test needs the network."""
from __future__ import annotations

import json, shutil, subprocess, sys, unittest

from addystack_home import KIT, Home

# The kit files the addystack tool runs from.
TOOL = ["bin", "lib", "hooks", "schema", "core", "addystack.defaults.jsonc"]

# A stand-in for `npx skills`, as skills v1.7.6 behaves for these commands: `add SOURCE -g -y
# --skill NAME…` copies each skill from SOURCE's HEAD, or with SOURCE#REF from REF, into
# ~/.agents/skills, links Claude Code's folder to it, and records it in the lock with its
# ref; `update -g -y` recopies every locked skill its source, at its ref, still has, and
# for a source it can't read prints `✗ Failed to check skills from SOURCE` and still exits 0;
# `remove NAME… -g -y` deletes them. It logs each call. A file named fail-add in HOME makes
# the next add fail, once.
STUB = r'''
import json, os, pathlib, shutil, subprocess, sys, tempfile
home = pathlib.Path(os.environ["HOME"])
lock_path = pathlib.Path(os.environ["XDG_STATE_HOME"], "skills", ".skill-lock.json")
with open(home / "skills-cli.log", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if "-g" not in args or "-y" not in args:
    sys.exit("needs -g -y")
lock = json.loads(lock_path.read_text()) if lock_path.exists() else {"version": 3, "skills": {}}
agents, claude = home / ".agents/skills", home / ".claude/skills"

def install(source, names, ref=None):
    with tempfile.TemporaryDirectory() as tree:
        archive = subprocess.run(["git", "-C", source, "archive", ref or "HEAD"], capture_output=True,
                                 check=True).stdout
        subprocess.run(["tar", "-x", "-C", tree], input=archive, check=True)
        for name in names:
            if not pathlib.Path(tree, name).is_dir():
                continue
            shutil.rmtree(agents / name, ignore_errors=True)
            shutil.copytree(pathlib.Path(tree, name), agents / name)
            claude.mkdir(parents=True, exist_ok=True)
            if not (claude / name).is_symlink():
                (claude / name).symlink_to(f"../../.agents/skills/{name}")
            lock["skills"][name] = {"source": source, "sourceType": "local", **({"ref": ref} if ref else {})}

command = args[0]
if command == "add" and (home / "fail-add").exists():
    (home / "fail-add").unlink()
    sys.exit("add failed")
if command == "add":
    names = []
    for arg in args[args.index("--skill") + 1:]:
        if arg.startswith("-"):
            break
        names.append(arg)
    source, _, ref = args[1].partition("#")
    install(source, names, ref or None)
elif command == "update":
    for source, ref in {(entry["source"], entry.get("ref")) for entry in lock["skills"].values()}:
        try:
            install(source, [name for name, entry in lock["skills"].items()
                             if (entry["source"], entry.get("ref")) == (source, ref)], ref)
        except subprocess.CalledProcessError:
            print(f"  \x1b[38;5;102m✗ Failed to check skills from {source}\x1b[0m")
elif command == "remove":
    for name in [a for a in args[1:] if not a.startswith("-")]:
        shutil.rmtree(agents / name, ignore_errors=True)
        if (claude / name).is_symlink():
            (claude / name).unlink()
        lock["skills"].pop(name, None)
lock_path.parent.mkdir(parents=True, exist_ok=True)
lock_path.write_text(json.dumps(lock, indent=2))
'''


class Update(Home):
    linked = False

    def setUp(self):
        super().setUp()
        self.write(self.home / ".gitconfig", "[user]\n\tname = Sam\n\temail = sam@example.com\n"
                                             "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n")

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                              env=self.env).stdout.strip()

    def tool(self, folder, skills):
        """The addystack tool's files in folder, with a release list of these skills."""
        for name in TOOL:
            source = KIT / name
            if source.is_dir():
                shutil.copytree(source, folder / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copy(source, folder / name)
        (folder / "core" / "skills.json").write_text(json.dumps({"skills": skills}))

    def release(self, repo, skills, tag):
        """Commits a release of the kit holding these {skill: layer} skills and an addystack
        skill with the tool, and tags it."""
        for child in repo.iterdir() if repo.exists() else ():
            if child.name != ".git":
                shutil.rmtree(child)
        self.tool(repo / "addystack", skills)
        self.write(repo / "addystack" / "SKILL.md", "---\nname: addystack\n---\n")
        for name, layer in skills.items():
            self.write(repo / name / "SKILL.md", f"---\nname: {name}\nmetadata:\n  layer: {layer}\n---\n{tag}\n")
        if not (repo / ".git").exists():
            self.git(repo, "init", "-q")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", tag)
        self.git(repo, "tag", tag)


class SkillsInstall(Update):
    """Plan check 10."""

    def setUp(self):
        super().setUp()
        self.stub("skills", f'exec "{sys.executable}" "{self.home / "stub.py"}" "$@"')
        self.write(self.home / "stub.py", STUB)
        self.env["ADDYSTACK_SKILLS_CLI"] = str(self.stubs / "skills")
        self.repo = self.home / "release"
        self.release(self.repo, {"alpha": "primitive", "beta": "primitive", "extra": "optional"}, "v0.1.0")
        # A skill of the user's own, from another source, which update leaves alone.
        self.mine = self.home / "mine"
        self.write(self.mine / "mine" / "SKILL.md", "---\nname: mine\n---\n")
        self.git(self.mine, "init", "-q")
        self.git(self.mine, "add", "-A")
        self.git(self.mine, "commit", "-q", "-m", "mine")
        for source, names in [(self.repo, ["addystack", "alpha", "beta", "extra"]), (self.mine, ["mine"])]:
            subprocess.run([self.stubs / "skills", "add", str(source), "-g", "-y", "--skill", *names], check=True,
                           env=self.env)
        self.kit = self.home / ".agents/skills/addystack"
        self.ok("install", bin_=self.kit / "bin" / "addystack")
        (self.home / "skills-cli.log").unlink()

    def installed(self, folder):
        return sorted(path.name for path in (self.home / folder).iterdir())

    def test_installs_the_added_core_skill_and_removes_the_dropped_one_without_a_terminal(self):
        self.release(self.repo, {"alpha": "primitive", "gamma": "orchestrator", "extra": "optional"}, "v0.2.0")
        result = self.ok("update", bin_=self.kit / "bin" / "addystack")
        for folder in (".agents/skills", ".claude/skills"):
            self.assertEqual(self.installed(folder), ["addystack", "alpha", "extra", "gamma", "mine"])
        self.assertIn("v0.2.0", (self.home / ".agents/skills/alpha/SKILL.md").read_text())
        calls = [json.loads(line) for line in (self.home / "skills-cli.log").read_text().splitlines()]
        self.assertEqual(calls, [["update", "-g", "-y"], ["add", str(self.repo), "-g", "-y", "--skill", "gamma"],
                                 ["remove", "beta", "-g", "-y"]])
        self.assertIn("ok    skill links: 2 core skills", result.stdout)
        self.assertIn("ok    hooks: match the selection", result.stdout)

    def test_a_core_skill_the_user_removed_stays_removed(self):
        subprocess.run([self.stubs / "skills", "remove", "beta", "-g", "-y"], check=True, env=self.env)
        (self.home / "skills-cli.log").unlink()
        self.release(self.repo, {"alpha": "primitive", "beta": "primitive", "gamma": "primitive"}, "v0.2.0")
        self.cli("update", bin_=self.kit / "bin" / "addystack")
        self.assertNotIn("beta", self.installed(".agents/skills"))
        calls = [json.loads(line) for line in (self.home / "skills-cli.log").read_text().splitlines()]
        self.assertIn(["add", str(self.repo), "-g", "-y", "--skill", "gamma"], calls)

    def test_an_optional_skill_made_core_is_added(self):
        subprocess.run([self.stubs / "skills", "remove", "extra", "-g", "-y"], check=True, env=self.env)
        (self.home / "skills-cli.log").unlink()
        self.release(self.repo, {"alpha": "primitive", "beta": "primitive", "extra": "primitive"}, "v0.2.0")
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(self.calls(), [["update", "-g", "-y"],
                                        ["add", str(self.repo), "-g", "-y", "--skill", "extra"]])

    def test_only_a_skill_that_was_core_is_removed_when_dropped_or_made_optional(self):
        # extra was optional, so dropping it leaves the user's copy; beta goes from core to optional.
        self.release(self.repo, {"alpha": "primitive", "beta": "optional"}, "v0.2.0")
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(self.calls(), [["update", "-g", "-y"], ["remove", "beta", "-g", "-y"]])
        self.assertIn("extra", self.installed(".agents/skills"))

    def test_adds_from_the_ref_the_kit_was_installed_from(self):
        # The kit came from a feature branch, which then gets a release with gamma; main doesn't.
        self.git(self.repo, "branch", "feature")
        subprocess.run([self.stubs / "skills", "add", f"{self.repo}#feature", "-g", "-y", "--skill", "addystack"],
                       check=True, env=self.env)
        (self.home / "skills-cli.log").unlink()
        self.git(self.repo, "checkout", "-q", "feature")
        self.release(self.repo, {"alpha": "primitive", "beta": "primitive", "gamma": "primitive"}, "v0.2.0-feature")
        self.git(self.repo, "checkout", "-q", "main")
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertIn(["add", f"{self.repo}#feature", "-g", "-y", "--skill", "gamma"], self.calls())
        self.assertIn("v0.2.0-feature", (self.home / ".agents/skills/gamma/SKILL.md").read_text())

    def test_a_source_the_skills_cli_couldnt_check_fails_the_update(self):
        self.release(self.repo, {"alpha": "primitive", "beta": "primitive", "gamma": "primitive"}, "v0.2.0")
        self.repo.rename(self.home / "offline")
        result = self.cli("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"Failed to check skills from {self.repo}", result.stdout)
        self.assertIn("skills update couldn't check every source", result.stderr)
        self.assertEqual(self.calls(), [["update", "-g", "-y"]])

    def test_a_release_with_no_change_only_updates(self):
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        calls = (self.home / "skills-cli.log").read_text().splitlines()
        self.assertEqual(calls, ['["update", "-g", "-y"]'])

    def calls(self):
        log = self.home / "skills-cli.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def assert_removed_nothing(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertIn("core/skills.json", result.stderr)
        self.assertIn("no skill was added or removed", result.stderr)
        self.assertEqual([call for call in self.calls() if call[0] != "update"], [])
        self.assertEqual(self.installed(".agents/skills"), ["addystack", "alpha", "beta", "extra", "mine"])

    def test_an_installed_release_list_it_cant_read_removes_nothing(self):
        (self.kit / "core/skills.json").unlink()
        self.release(self.repo, {"alpha": "primitive", "gamma": "primitive"}, "v0.2.0")
        self.assert_removed_nothing(self.cli("update", bin_=self.kit / "bin" / "addystack"))

    def test_a_new_release_list_it_cant_read_removes_nothing(self):
        self.release(self.repo, {"alpha": "primitive", "gamma": "primitive"}, "v0.2.0")
        (self.repo / "addystack/core/skills.json").write_text("{ not json")
        self.git(self.repo, "commit", "-q", "-am", "broken list")
        self.assert_removed_nothing(self.cli("update", bin_=self.kit / "bin" / "addystack"))

    def test_the_kits_source_is_the_addystack_skills_own_even_when_most_names_come_from_elsewhere(self):
        # The user installed their own alpha, beta, and extra from another repo.
        other = self.home / "other"
        for name in ("alpha", "beta", "extra"):
            self.write(other / name / "SKILL.md", f"---\nname: {name}\n---\ntheirs\n")
        self.git(other, "init", "-q")
        self.git(other, "add", "-A")
        self.git(other, "commit", "-q", "-m", "theirs")
        subprocess.run([self.stubs / "skills", "add", str(other), "-g", "-y", "--skill", "alpha", "beta", "extra"],
                       check=True, env=self.env)
        (self.home / "skills-cli.log").unlink()
        self.release(self.repo, {"alpha": "primitive", "gamma": "primitive"}, "v0.2.0")
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(self.calls(), [["update", "-g", "-y"],
                                        ["add", str(self.repo), "-g", "-y", "--skill", "gamma"]])
        self.assertIn("theirs", (self.home / ".agents/skills/beta/SKILL.md").read_text())

    def test_a_retry_after_a_failed_add_finishes_the_same_change(self):
        self.release(self.repo, {"alpha": "primitive", "gamma": "primitive", "extra": "optional"}, "v0.2.0")
        self.write(self.home / "fail-add", "")
        self.assertEqual(self.cli("update", bin_=self.kit / "bin" / "addystack").returncode, 1)
        self.assertEqual(self.installed(".agents/skills"), ["addystack", "alpha", "beta", "extra", "mine"])
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(self.installed(".agents/skills"), ["addystack", "alpha", "extra", "gamma", "mine"])
        self.assertEqual(self.calls()[-2:], [["add", str(self.repo), "-g", "-y", "--skill", "gamma"],
                                             ["remove", "beta", "-g", "-y"]])
        # Once it finished, the next update starts from the release it installed.
        self.ok("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(self.calls()[-1], ["update", "-g", "-y"])

    def test_fails_without_the_addystack_skills_lock_entry(self):
        lock = self.home / ".local/state/skills/.skill-lock.json"
        entries = json.loads(lock.read_text())
        del entries["skills"]["addystack"]
        lock.write_text(json.dumps(entries))
        result = self.cli("update", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no entry for the addystack skill", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_to_needs_a_checkout(self):
        result = self.cli("update", "--to", "v0.1.0", bin_=self.kit / "bin" / "addystack")
        self.assertEqual(result.returncode, 2)


class Checkout(Update):
    """A maintainer's git checkout of the kit."""

    def setUp(self):
        super().setUp()
        self.upstream = self.home / "upstream"
        self.tool(self.upstream, {})
        self.git(self.upstream, "init", "-q")
        for tag in ("v0.1.0", "v0.2.0", "v0.10.0"):
            (self.upstream / "VERSION").write_text(tag)
            self.git(self.upstream, "add", "-A")
            self.git(self.upstream, "commit", "-q", "-m", tag)
            self.git(self.upstream, "tag", tag)
        self.checkout = self.home / "checkout"
        subprocess.run(["git", "clone", "-q", "--no-tags", str(self.upstream), str(self.checkout)], check=True,
                       env=self.env)
        self.git(self.checkout, "checkout", "-q", "--detach", "HEAD~2")
        self.bin = self.checkout / "bin" / "addystack"

    def test_checks_out_the_newest_tag_then_installs(self):
        result = self.ok("update", bin_=self.bin)
        self.assertEqual((self.checkout / "VERSION").read_text(), "v0.10.0")
        self.assertIn("checked out v0.10.0", result.stdout)
        # The checkout is under HOME, so its hooks run from ~/checkout.
        self.assertIn('"~/checkout/hooks/merge-gate.py"', self.settings.read_text())
        self.assertIn("ok    hooks: match the selection", result.stdout)

    def test_to_checks_out_that_tag(self):
        self.ok("update", "--to", "v0.2.0", bin_=self.bin)
        self.assertEqual((self.checkout / "VERSION").read_text(), "v0.2.0")

    def test_refuses_a_checkout_with_uncommitted_changes(self):
        (self.checkout / "VERSION").write_text("edited")
        result = self.cli("update", bin_=self.bin)
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertEqual((self.checkout / "VERSION").read_text(), "edited")


if __name__ == "__main__":
    unittest.main()

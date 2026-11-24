"""Tests for .githooks/pre-push: it runs the test suites as dagger check when Dagger
reaches an engine, blocks the push when a check fails, when the module doesn't load, or
when a pattern matches no check, and runs them on the host when dagger or its engine is
missing; its macos_only list names every hook test that skips off macOS, since only that
list runs on the Mac; and for .githooks/pre-commit: it runs only the touched folders'
suites on the host, and never Dagger."""
import ast, os, pathlib, re, shutil, subprocess, tempfile, unittest

KIT = pathlib.Path(__file__).resolve().parent.parent
HOOK = KIT / ".githooks" / "pre-push"
PRE_COMMIT = KIT / ".githooks" / "pre-commit"
# Whether /bin/bash is older than 4, as macOS ships it.
BASH_3 = os.path.exists("/bin/bash") and int(subprocess.run(
    ["/bin/bash", "--norc", "--noprofile", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True,
    env={k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "ENV")}).stdout.split()[-1]) < 4


def darwin_only(decorator, names):
    """Whether the decorator is skipUnless(sys.platform == "darwin", …) or a name bound to it."""
    if isinstance(decorator, ast.Name):
        return decorator.id in names
    return (isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", None) == "skipUnless"
            and "darwin" in ast.unparse(decorator.args[0]))


def macos_tests():
    """Each test class or method in hooks/test_*.py that only runs on macOS, as a unittest name."""
    found = set()
    for path in sorted((KIT / "skills" / "primitive" / "addystack" / "hooks").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        names = {target.id for node in tree.body if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name) and darwin_only(node.value, ())}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if any(darwin_only(d, names) for d in node.decorator_list):
                found.add(f"{path.stem}.{node.name}")
                continue
            found |= {f"{path.stem}.{node.name}.{item.name}" for item in node.body
                      if isinstance(item, ast.FunctionDef) and any(darwin_only(d, names) for d in item.decorator_list)}
    return found


# A dagger that logs each call. `core version` exits DAGGER_ENGINE. `check -l` hangs with
# DAGGER_HANG set, as with an engine stuck restarting, and fails when
# the engine or the module (DAGGER_MODULE) does, and otherwise lists DAGGER_LIST's names
# under a header, as the real one does. `check` exits DAGGER_CHECK.
FAKE_DAGGER = """#!/bin/sh
echo "$*" >> "$DAGGER_LOG"
case $1 in
  core) exit "$DAGGER_ENGINE" ;;
  check)
    if [ "$2" = -l ]; then
      [ -z "$DAGGER_HANG" ] || sleep 30
      [ "$DAGGER_ENGINE" = 0 ] && [ "$DAGGER_MODULE" = 0 ] || exit 1
      echo "Name  Description"
      for name in $DAGGER_LIST; do echo "$name  a suite"; done
      exit 0
    fi
    [ "$DAGGER_CHECK" = 0 ] || echo "a check failed"; exit "$DAGGER_CHECK" ;;
esac
"""
LIST = "check -l -s skills:*-tests skills:suites-listed"
RUN = "check -qq skills:*-tests skills:suites-listed"


class DaggerOrHost(unittest.TestCase):
    """The real hook in a scratch repo whose lints pass, whose hook inputs aren't staged,
    and whose one host suite leaves a file behind when it runs."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = pathlib.Path(self.folder.name, "repo")
        (self.repo / ".githooks").mkdir(parents=True)
        for hook in (HOOK, PRE_COMMIT, KIT / ".githooks" / "suites.sh"):
            shutil.copy(hook, self.repo / ".githooks" / hook.name)
        lints = ["check-frontmatter.sh", "check-skill-size.sh", "check-layers.py", "check-neutral.py", "check-links.py", "sync-format.sh",
                 "sync-notes.py", "sync-skill-list.py", "sync-copies.py", "check_examples.py",
                 "check-reply-budget.py"]
        self.script("hook-inputs-staged.sh", "exit 1")
        for lint in lints:
            self.script(lint, "exit 0")
        self.ran = pathlib.Path(self.folder.name, "host-suites-ran")
        (self.repo / "scripts" / "test_host.py").write_text(
            "import os, pathlib, unittest\n"
            "class Host(unittest.TestCase):\n"
            "    def test_runs(self):\n"
            "        pathlib.Path(os.environ['HOST_RAN']).touch()\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        # The hook runs the copy check from the index, so its stub must be staged.
        subprocess.run(["git", "add", "scripts/sync-copies.py"], cwd=self.repo, check=True)
        self.bin = pathlib.Path(self.folder.name, "bin")
        self.bin.mkdir()
        for tool in ("python3", "git", "bash", "uname", "cut", "mktemp"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.log = pathlib.Path(self.folder.name, "dagger.log")

    def script(self, name, body):
        path = self.repo / "scripts" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def push(self, engine=0, check=0, module=0, listed="skills:my-inbox-tests skills:suites-listed",
               dagger=True, **extra):
        if dagger:
            (self.bin / "dagger").write_text(FAKE_DAGGER)
            (self.bin / "dagger").chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        untracked = extra.pop("UNTRACKED", ())
        env.update(PATH=f"{self.bin}:/usr/bin:/bin", DAGGER_LOG=str(self.log), DAGGER_ENGINE=str(engine),
                   DAGGER_CHECK=str(check), DAGGER_MODULE=str(module), DAGGER_LIST=listed,
                   HOST_RAN=str(self.ran), **extra)
        # The push sends HEAD, committed with whatever the test changed, so the hook checks
        # this checkout; a push from a dirty one checks a scratch worktree of the tip.
        subprocess.run(["git", "add", "-A"], cwd=self.repo, env=env, check=True)
        for path in untracked:  # left out of the push, as a file not committed yet
            subprocess.run(["git", "rm", "-q", "--cached", path], cwd=self.repo, env=env, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                        "--no-verify", "-m", "push"], cwd=self.repo, env=env, check=True)
        tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, env=env, capture_output=True, text=True).stdout
        run = subprocess.run([str(self.repo / ".githooks" / "pre-push"), "origin", "url"], cwd=self.repo, env=env,
                             input=f"refs/heads/main {tip.strip()} refs/heads/main {'0' * 40}\n",
                             capture_output=True, text=True)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return run, calls

    def test_a_reachable_engine_runs_the_checks_and_skips_the_host_suites(self):
        run, calls = self.push()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, [LIST, RUN])
        self.assertFalse(self.ran.exists())

    def test_a_failed_check_blocks_the_commit(self):
        run, calls = self.push(check=1)
        self.assertEqual(run.returncode, 1)
        self.assertIn("a Dagger check failed", run.stderr)
        self.assertFalse(self.ran.exists())

    def test_without_an_engine_the_host_suites_run(self):
        run, calls = self.push(engine=1)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Dagger can't reach its engine", run.stdout)
        self.assertEqual(calls, [LIST, "core version"])
        self.assertTrue(self.ran.exists())

    def test_an_engine_that_doesnt_answer_runs_the_host_suites(self):
        run, calls = self.push(DAGGER_HANG="1", PRE_COMMIT_DAGGER_WAIT="2")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Dagger's engine didn't answer in 2s", run.stdout)
        self.assertEqual(calls, [LIST])
        self.assertTrue(self.ran.exists())

    def test_a_wait_that_isnt_whole_seconds_blocks_the_commit(self):
        # `3m` made the wait's `[ -ge ]` fail on every poll, so a hung engine never timed out.
        for wait in ["3m", "1.5", "-1"]:
            with self.subTest(wait=wait):
                run, calls = self.push(DAGGER_HANG="1", PRE_COMMIT_DAGGER_WAIT=wait)
                self.assertEqual(run.returncode, 1)
                self.assertIn(f"PRE_COMMIT_DAGGER_WAIT is whole seconds, such as 180, not '{wait}'", run.stderr)
                self.assertEqual(calls, [])

    def test_a_module_that_doesnt_load_blocks_the_commit(self):
        run, calls = self.push(module=1)
        self.assertEqual(run.returncode, 1)
        self.assertIn("the Dagger module didn't load", run.stderr)
        self.assertEqual(calls, [LIST, "core version"])
        self.assertFalse(self.ran.exists())

    def test_patterns_no_check_matches_block_the_commit(self):
        # dagger check runs nothing for them and exits 0, as after renaming the module.
        run, calls = self.push(listed="")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no Dagger check matches skills:*-tests skills:suites-listed;", run.stderr)
        self.assertEqual(calls, [LIST])

    def test_one_pattern_matching_nothing_blocks_the_commit(self):
        run, calls = self.push(listed="skills:my-inbox-tests")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no Dagger check matches skills:suites-listed;", run.stderr)
        self.assertEqual(calls, [LIST])

    def test_checks_the_committed_tip_not_the_checkouts_other_files(self):
        # Review of #103: a suite that passes only on an untracked file in this checkout must
        # fail the push, since the tip it sends lacks the file; and a failing host suite in
        # the scratch worktree that check runs in must fail it too.
        (self.repo / "scripts" / "helper.py").write_text("VALUE = 1\n")
        (self.repo / "scripts" / "test_uses_helper.py").write_text(
            "import unittest, helper\nclass T(unittest.TestCase):\n    def test_it(self):\n"
            "        self.assertEqual(helper.VALUE, 1)\n")
        run, _ = self.push(dagger=False, UNTRACKED=["scripts/helper.py"])
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("helper", run.stderr)
        worktrees = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertEqual(len(worktrees.splitlines()), 1)  # the scratch worktree is gone

    def test_without_dagger_the_host_suites_run(self):
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("dagger isn't installed", run.stdout)
        self.assertTrue(self.ran.exists())

    @unittest.skipUnless(BASH_3, "needs /bin/bash older than 4, as on macOS")
    def test_bash_3_runs_a_skill_suite_on_the_host(self):
        # bash 3.2 does no brace expansion inside `local name=(…)`, so the folder list
        # once collapsed to one path that matched nothing.
        skill = self.repo / "skills" / "primitive" / "my-skill" / "scripts"
        skill.mkdir(parents=True)
        skill_ran = pathlib.Path(self.folder.name, "skill-suite-ran")
        (skill / "test_skill.py").write_text(
            "import pathlib, unittest\n"
            "class Skill(unittest.TestCase):\n"
            "    def test_runs(self):\n"
            f"        pathlib.Path({str(skill_ran)!r}).touch()\n")
        (self.bin / "bash").unlink()
        (self.bin / "bash").symlink_to("/bin/bash")
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(skill_ran.exists())
        self.assertTrue(self.ran.exists())

    def test_a_checkout_path_with_glob_characters_runs_its_suites(self):
        moved = pathlib.Path(self.folder.name, "re[p]o")
        self.repo.rename(moved)
        self.repo = moved
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_a_dangling_first_test_file_still_runs_its_folder(self):
        (self.repo / "scripts" / "test_000_broken.py").symlink_to("absent.py")
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_inherited_glob_settings_still_run_the_host_suites(self):
        startup = pathlib.Path(self.folder.name, "bash-env")
        # The real path, since git, and so the hook's root, resolves /var to /private/var.
        hidden = pathlib.Path(os.path.realpath(self.repo), "scripts", "test_host.py")
        startup.write_text(f"shopt -s nullglob\nGLOBIGNORE='{hidden}'\n")
        os.environ["BASH_ENV"] = str(startup)
        self.addCleanup(os.environ.pop, "BASH_ENV")
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_no_host_suite_blocks_the_commit(self):
        (self.repo / "scripts" / "test_host.py").unlink()
        run, _ = self.push(dagger=False)
        self.assertEqual(run.returncode, 1)
        self.assertIn("pre-commit: no host test suite ran", run.stderr)
        self.assertIn("skills/primitive/*/scripts", run.stderr)
        self.assertIn(" scripts;", run.stderr)
        self.assertFalse(self.ran.exists())


class PreCommit(unittest.TestCase):
    """The real pre-commit in a scratch repo whose lints pass: it runs the suites of the
    folders the commit stages, on the host, and leaves Dagger to pre-push."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = pathlib.Path(self.folder.name, "repo")
        (self.repo / ".githooks").mkdir(parents=True)
        for hook in (PRE_COMMIT, KIT / ".githooks" / "suites.sh"):
            shutil.copy(hook, self.repo / ".githooks" / hook.name)
        for lint in ["check-frontmatter.sh", "check-skill-size.sh", "check-layers.py", "check-neutral.py",
                     "check-links.py", "sync-format.sh", "sync-notes.py", "sync-skill-list.py", "sync-copies.py",
                     "check_examples.py", "check-reply-budget.py"]:
            self.write(f"scripts/{lint}", "#!/bin/sh\nexit 0\n").chmod(0o755)
        self.write("scripts/hook-inputs-staged.sh", "#!/bin/sh\nexit 1\n").chmod(0o755)
        self.ran = {}
        for folder in ["scripts", "shared/scripts", "skills/primitive/one/scripts", "skills/orchestrator/two/scripts",
                       "maintainer"]:
            self.ran[folder] = pathlib.Path(self.folder.name, folder.replace("/", "-") + "-ran")
            self.write(f"{folder}/test_{folder.replace('/', '_')}.py",
                       "import pathlib, unittest\nclass T(unittest.TestCase):\n    def test_runs(self):\n"
                       f"        pathlib.Path({str(self.ran[folder])!r}).touch()\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", "base")
        self.bin = pathlib.Path(self.folder.name, "bin")
        self.bin.mkdir()
        (self.bin / "dagger").write_text("#!/bin/sh\necho dagger >> \"$DAGGER_LOG\"\nexit 1\n")
        (self.bin / "dagger").chmod(0o755)
        self.log = pathlib.Path(self.folder.name, "dagger.log")

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def commit(self, *paths):
        for name in paths:
            self.write(name, "changed\n")
        self.git("add", "-A")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(PATH=f"{self.bin}:{env['PATH']}", DAGGER_LOG=str(self.log))
        run = subprocess.run(["git", "-c", "core.hooksPath=.githooks", "-c", "user.name=t", "-c", "user.email=t@t",
                              "commit", "-q", "-m", "change"], cwd=self.repo, env=env, capture_output=True, text=True)
        return run, sorted(folder for folder, ran in self.ran.items() if ran.exists())

    def test_runs_the_touched_skills_suite_and_never_dagger(self):
        run, ran = self.commit("skills/primitive/one/SKILL.md")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(ran, ["maintainer", "skills/primitive/one/scripts"])  # the workshop's always run
        self.assertFalse(self.log.exists())

    def test_maps_each_staged_path_to_its_folders_suite(self):
        run, ran = self.commit("shared/views.md", "scripts/check-x.py", "skills/orchestrator/two/references/a.md")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(ran, ["maintainer", "scripts", "shared/scripts", "skills/orchestrator/two/scripts"])

    def test_a_docs_only_commit_runs_no_kit_suite(self):
        run, ran = self.commit("README.md", "CHANGELOG.md")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(ran, ["maintainer"])

    def test_a_failing_touched_suite_blocks_the_commit(self):
        self.write("skills/primitive/one/scripts/test_fail.py",
                   "import unittest\nclass F(unittest.TestCase):\n    def test_fails(self):\n        self.fail('x')\n")
        run, _ = self.commit("skills/primitive/one/scripts/test_fail.py")
        self.assertNotEqual(run.returncode, 0)


class MacosOnly(unittest.TestCase):
    def test_finds_the_keychain_guard(self):
        self.assertIn("test_hooks.KeychainHomeGuard", macos_tests())

    def test_the_hook_runs_every_macos_only_hook_test(self):
        listed = re.search(r"macos_only=\(([^)]*)\)", HOOK.read_text()).group(1).split()
        self.assertEqual(sorted(listed), sorted(macos_tests()))


if __name__ == "__main__":
    unittest.main()

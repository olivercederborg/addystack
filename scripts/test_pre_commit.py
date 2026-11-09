"""Tests for .githooks/pre-commit: it runs the test suites as dagger check when Dagger
reaches an engine, blocks the commit when a check fails, when the module doesn't load, or
when a pattern matches no check, and runs them on the host when dagger or its engine is
missing; and its macos_only list names every hook test that skips off macOS, since only
that list runs on the Mac."""
import ast, os, pathlib, re, shutil, subprocess, tempfile, unittest

KIT = pathlib.Path(__file__).resolve().parent.parent
HOOK = KIT / ".githooks" / "pre-commit"
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
        shutil.copy(HOOK, self.repo / ".githooks" / "pre-commit")
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
        for tool in ("python3", "git", "bash", "uname"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.log = pathlib.Path(self.folder.name, "dagger.log")

    def script(self, name, body):
        path = self.repo / "scripts" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def commit(self, engine=0, check=0, module=0, listed="skills:my-inbox-tests skills:suites-listed",
               dagger=True, **extra):
        if dagger:
            (self.bin / "dagger").write_text(FAKE_DAGGER)
            (self.bin / "dagger").chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(PATH=f"{self.bin}:/usr/bin:/bin", DAGGER_LOG=str(self.log), DAGGER_ENGINE=str(engine),
                   DAGGER_CHECK=str(check), DAGGER_MODULE=str(module), DAGGER_LIST=listed,
                   HOST_RAN=str(self.ran), **extra)
        run = subprocess.run([str(self.repo / ".githooks" / "pre-commit")], cwd=self.repo, env=env,
                             capture_output=True, text=True)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return run, calls

    def test_a_reachable_engine_runs_the_checks_and_skips_the_host_suites(self):
        run, calls = self.commit()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, [LIST, RUN])
        self.assertFalse(self.ran.exists())

    def test_a_failed_check_blocks_the_commit(self):
        run, calls = self.commit(check=1)
        self.assertEqual(run.returncode, 1)
        self.assertIn("a Dagger check failed", run.stderr)
        self.assertFalse(self.ran.exists())

    def test_without_an_engine_the_host_suites_run(self):
        run, calls = self.commit(engine=1)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Dagger can't reach its engine", run.stdout)
        self.assertEqual(calls, [LIST, "core version"])
        self.assertTrue(self.ran.exists())

    def test_an_engine_that_doesnt_answer_runs_the_host_suites(self):
        run, calls = self.commit(DAGGER_HANG="1", PRE_COMMIT_DAGGER_WAIT="2")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Dagger's engine didn't answer in 2s", run.stdout)
        self.assertEqual(calls, [LIST])
        self.assertTrue(self.ran.exists())

    def test_a_wait_that_isnt_whole_seconds_blocks_the_commit(self):
        # `3m` made the wait's `[ -ge ]` fail on every poll, so a hung engine never timed out.
        for wait in ["3m", "1.5", "-1"]:
            with self.subTest(wait=wait):
                run, calls = self.commit(DAGGER_HANG="1", PRE_COMMIT_DAGGER_WAIT=wait)
                self.assertEqual(run.returncode, 1)
                self.assertIn(f"PRE_COMMIT_DAGGER_WAIT is whole seconds, such as 180, not '{wait}'", run.stderr)
                self.assertEqual(calls, [])

    def test_a_module_that_doesnt_load_blocks_the_commit(self):
        run, calls = self.commit(module=1)
        self.assertEqual(run.returncode, 1)
        self.assertIn("the Dagger module didn't load", run.stderr)
        self.assertEqual(calls, [LIST, "core version"])
        self.assertFalse(self.ran.exists())

    def test_patterns_no_check_matches_block_the_commit(self):
        # dagger check runs nothing for them and exits 0, as after renaming the module.
        run, calls = self.commit(listed="")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no Dagger check matches skills:*-tests skills:suites-listed;", run.stderr)
        self.assertEqual(calls, [LIST])

    def test_one_pattern_matching_nothing_blocks_the_commit(self):
        run, calls = self.commit(listed="skills:my-inbox-tests")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no Dagger check matches skills:suites-listed;", run.stderr)
        self.assertEqual(calls, [LIST])

    def test_a_workshop_suite_runs_here_beside_the_dagger_checks(self):
        workshop = pathlib.Path(self.folder.name, "workshop-ran")
        (self.repo / "maintainer").mkdir()
        (self.repo / "maintainer" / "test_workshop.py").write_text(
            "import os, pathlib, unittest\n"
            "class Workshop(unittest.TestCase):\n"
            "    def test_runs(self):\n"
            f"        pathlib.Path({str(workshop)!r}).touch()\n")
        run, calls = self.commit()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(calls, [LIST, RUN])
        self.assertTrue(workshop.exists())
        self.assertFalse(self.ran.exists())

    def test_without_dagger_the_host_suites_run(self):
        run, _ = self.commit(dagger=False)
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
        run, _ = self.commit(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(skill_ran.exists())
        self.assertTrue(self.ran.exists())

    def test_a_checkout_path_with_glob_characters_runs_its_suites(self):
        moved = pathlib.Path(self.folder.name, "re[p]o")
        self.repo.rename(moved)
        self.repo = moved
        run, _ = self.commit(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_a_dangling_first_test_file_still_runs_its_folder(self):
        (self.repo / "scripts" / "test_000_broken.py").symlink_to("absent.py")
        run, _ = self.commit(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_inherited_glob_settings_still_run_the_host_suites(self):
        startup = pathlib.Path(self.folder.name, "bash-env")
        # The real path, since git, and so the hook's root, resolves /var to /private/var.
        hidden = pathlib.Path(os.path.realpath(self.repo), "scripts", "test_host.py")
        startup.write_text(f"shopt -s nullglob\nGLOBIGNORE='{hidden}'\n")
        os.environ["BASH_ENV"] = str(startup)
        self.addCleanup(os.environ.pop, "BASH_ENV")
        run, _ = self.commit(dagger=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(self.ran.exists())

    def test_no_host_suite_blocks_the_commit(self):
        (self.repo / "scripts" / "test_host.py").unlink()
        run, _ = self.commit(dagger=False)
        self.assertEqual(run.returncode, 1)
        self.assertIn("pre-commit: no host test suite ran", run.stderr)
        self.assertIn("skills/primitive/*/scripts", run.stderr)
        self.assertIn(" scripts;", run.stderr)
        self.assertFalse(self.ran.exists())


class MacosOnly(unittest.TestCase):
    def test_finds_the_keychain_guard(self):
        self.assertIn("test_hooks.KeychainHomeGuard", macos_tests())

    def test_the_hook_runs_every_macos_only_hook_test(self):
        listed = re.search(r"macos_only=\(([^)]*)\)", HOOK.read_text()).group(1).split()
        self.assertEqual(sorted(listed), sorted(macos_tests()))


if __name__ == "__main__":
    unittest.main()

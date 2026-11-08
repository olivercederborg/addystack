"""Tests for hook-inputs-staged.sh: a staged change to any file the hook tests depend on
says run, a docs-only or unstaged change says skip, and a `git commit <paths>` is read
from its temporary index."""
import os, pathlib, re, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "hook-inputs-staged.sh"
HOOKS = SCRIPT.parent.parent / "skills" / "primitive" / "addystack" / "hooks"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


KIT = "skills/primitive/addystack"


def outside_inputs():
    """Checkout paths outside the hooks folder that a hook or hook test names: in the kit as
    `HOOKS.parent / "a" / "b"` or `.parent.parent / "a" / "b"`, and in the checkout as
    `REPO / "a"` or `HOOKS.parents[3] / "a"`."""
    found = set()
    for source in HOOKS.glob("*.py"):
        text = source.read_text()
        for chain in re.findall(r'(?:HOOKS|parent)\.parent((?:\s*/\s*"[^"]+")+)', text):
            found.add("/".join([KIT, *re.findall(r'"([^"]+)"', chain)]))
        for chain in re.findall(r'(?:\bREPO|HOOKS\.parents\[3\])((?:\s*/\s*"[^"]+")+)', text):
            found.add("/".join(re.findall(r'"([^"]+)"', chain)))
    return sorted(found)


class HookInputsStaged(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.folder.name)
        self.git("init", "-q")
        for path in [f"{KIT}/hooks/a.py", "docs/notes.md", *outside_inputs()]:
            self.write(path)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.folder.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], cwd=self.repo, env=ENV, check=True, capture_output=True)

    def write(self, path, text="x\n"):
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text)

    def staged(self):
        return subprocess.run([str(SCRIPT)], cwd=self.repo, env=ENV, capture_output=True).returncode == 0

    def test_finds_the_outside_inputs(self):
        self.assertIn("skills/optional/reply-shape/SKILL.md", outside_inputs())

    def test_runs_for_each_input(self):
        for path in [f"{KIT}/hooks/a.py", f"{KIT}/hooks/new.py", *outside_inputs()]:
            with self.subTest(path=path):
                self.write(path, "changed\n")
                self.git("add", path)
                self.assertTrue(self.staged())
                self.git("reset", "-q", "--hard")
                self.git("clean", "-qfd")

    def test_runs_for_a_deletion_and_a_rename_out_of_hooks(self):
        self.git("rm", "-q", f"{KIT}/hooks/a.py")
        self.assertTrue(self.staged())
        self.git("reset", "-q", "--hard")
        self.git("mv", f"{KIT}/hooks/a.py", "docs/a.py")
        self.assertTrue(self.staged())

    def test_skips_a_docs_only_commit(self):
        self.write("docs/notes.md", "changed\n")
        self.git("add", "docs/notes.md")
        self.assertFalse(self.staged())

    def test_skips_an_unstaged_hooks_change(self):
        self.write(f"{KIT}/hooks/a.py", "changed\n")
        self.write("docs/notes.md", "changed\n")
        self.git("add", "docs/notes.md")
        self.assertFalse(self.staged())

    def test_reads_the_temporary_index_of_a_commit_with_paths(self):
        hook = self.repo / ".githooks" / "pre-commit"
        hook.parent.mkdir()
        hook.write_text(f'#!/bin/sh\n{SCRIPT} && echo run > "{self.repo}/result" || echo skip > "{self.repo}/result"\n')
        hook.chmod(0o755)
        self.git("config", "core.hooksPath", str(hook.parent))
        self.write(f"{KIT}/hooks/a.py", "changed\n")
        self.git("commit", "-q", "-m", "hooks", "--", f"{KIT}/hooks/a.py")
        self.assertEqual((self.repo / "result").read_text(), "run\n")
        self.write(f"{KIT}/hooks/a.py", "staged, not committed\n")
        self.git("add", f"{KIT}/hooks/a.py")
        self.write("docs/notes.md", "changed\n")
        self.git("commit", "-q", "-m", "docs", "--", "docs/notes.md")
        self.assertEqual((self.repo / "result").read_text(), "skip\n")


if __name__ == "__main__":
    unittest.main()
